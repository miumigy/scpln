# 統合Plan DB永続化 改修計画

- バージョン: 0.1（初稿）
- 最終更新: 2025-10-05
- 管理責任: Planning Hub プロダクトチーム（実装ドライバー: Codex CLI エージェント）

## 1. 目的
- 統合Planの成果物・入力スナップショット・編集履歴をRunRegistry同様にDBへ永続化し、版管理とトレーサビリティを強化する。
- CLI／API／バッチの実行経路を統一し、ファイル出力はオプション（エクスポート用途）へ移行する。
- KPI算出・差分比較・監査ログをDBクエリで完結できるよう基盤を整備し、運用負荷とデータ欠落リスクを低減する。

## 2. 現状整理
| 項目 | 永続化方式 | 主な格納先 | 課題 |
| --- | --- | --- | --- |
| Plan生成パイプライン（`scripts/plan_*.py`） | ファイルベースJSON | `out/*.json` | CLI実行が前提で、DB反映は後続の手動/呼び出し側実装に依存。再生成時の版管理が難しい。 |
| Plan UI/API (`POST /plans/integrated/run`) | JSONを`plan_artifacts`へ保存 | SQLite `plan_artifacts`（version_id,name,json_text） | JSON blobで保管されるため差分比較・行単位のロック・集計クエリを行えない。 |
| RunRegistry | SQLite `runs` / `run_configs` | `data/scpln.db` | `plan_version_id` 連携はあるがPlan側の粒度情報が欠落しクロス分析が困難。 |
| KPIレポート | CSV（`out/report.csv`） | ファイルシステム | 再読込や共有に手作業が必要。DBに永続化されず履歴管理が不十分。 |

## 3. 改修方針
- `plan_versions` をコアIDとして、以下の正規化テーブルを追加する。
  - `plan_series`（AGG/DET/MRPなどレベル別の時系列値）: 主キー `version_id, level, bucket_type, bucket_key, item_key, location_key`。指標列（demand, supply, backlog, inventory_open, inventory_close, prod_qty, ship_qty, capacity_used, cost_total など）を保持。
  - `plan_overrides`（UI編集・ロック・配分ウェイト）: `version_id, level, key_hash, payload_json, created_at, author`。
  - `plan_kpis`（KPIスナップショット）: `version_id, metric, value, unit, source_run_id`。
  - `plan_jobs`（Plan生成ジョブメタ）: `job_id, version_id, status, run_id, config_version_id, submitted_at`。
- `core/plan_repository`（仮称）を新設し、DB書き込み・読出し・差分適用を共通化。既存 `db.upsert_plan_artifact` は互換用に残しつつ段階的に縮退。
- Plan生成パイプラインは一時ファイルではなく `PlanRepository` へのストリーム書き込みを基本とし、必要時のみ `--export-dir` でJSON/CSVを出力する方針へ更新。
- RunRegistryとの連携を強化し、`run_id` を `plan_jobs` および `plan_series.source_run_id` に保持。Plan->Run->Planの再実行がDBキーのみで追跡できるようにする。
- 監視/バックアップは既存SQLite運用に揃え、`plan_series` 追加での容量増に備えて自動クリーニング/圧縮ポリシーを定義する。

## 4. フェーズ別タスク概要
| フェーズ | ステータス | 目的 | 主な成果物 | 完了条件 |
| --- | --- | --- | --- | --- |
| P0: 調査・コミットメント | todo | ステークホルダー合意と要件確定 | 要件サマリ, 非機能要件合意 | キックオフレビューで承認取得 |
| P1: スキーマ設計・Alembic | todo | 正規化テーブルとDDL決定 | DDL草案, Alembicマイグレーション, ER図 | Alembic適用とリバート試験が成功 |
| P2: 永続化レイヤ実装 | todo | PlanRepository実装とパイプライン書換 | `core/plan_repository.py`, サービス層, 単体テスト | CLI/API双方でDB書込みが行える |
| P3: UI/API/RunRegistry連携 | todo | UI/API実装の置換とRunRegistry連携強化 | `/plans` API改修, `/ui/plans` 表示更新, メトリクス拡張 | UIでのPlan閲覧/編集が新DB経路で成功 |
| P4: CLI・運用整備 | todo | CLI/バッチのDB化とドキュメント改訂 | 新CLIサブコマンド, Runbook更新 | Runbookに沿った再現テストが完了 |
| P5: 移行・検証・リリース | todo | 既存データ移行と段階的リリース | バックフィルスクリプト, リリースチェックリスト | Staging/Production切替が完了し監視が安定 |

## 5. フェーズ別詳細タスク

### P0: 調査・コミットメント
- [x] T0-1: 現行Plan利用フロー（UI/CLI/バッチ）の棚卸しとデータフロー図の更新。
  - UI: Planning Hub `/ui/plans` がPlan作成・参照・再整合の中心。`docs/TUTORIAL-JA.md` のステップ(1)〜(5)と `README.md` セクション「Planning Hub」で state 遷移・タブ構造・Plan & Run 連携を説明済み。`app/ui_plans.py` ではPlan成果物・RunリンクをDB(JSON)から読み出し、編集/ロックを `plan_artifacts` へ保存している。
  - API: `POST /plans/integrated/run`（`app/plans_api.py`）がaggregate→allocate→mrp→reconcile→artifact保存を順次実行し `plan_versions` を登録。`docs/API-OVERVIEW-JA.md` はPlanサマリ取得、比較CSV、再整合、Plan & Run自動補完などのエンドポイントを列挙。
  - CLI/バッチ: `scripts/run_planning_pipeline.sh` がAggregate〜Reportの一括実行を提供し、個別スクリプト群（`plan_aggregate.py`, `allocate.py`, `mrp.py`, `reconcile.py`, `report.py` 等）が `samples/planning` を入力にJSON/CSVを `out/` 配下へ出力。README「API & 実行エントリ」とTutorial「参考」でAPI/CLI利用例が案内されている。
- [x] T0-2: 利用部門ヒアリングの代わりに想定仕様を定義し、クエリ例・KPI粒度・保管期間を仮決めする。
  - 想定仕様は `docs/plan_db_assumed_requirements.md` にまとめ、粒度/KPI/保持ポリシー/連携要件を記載。
  - 想定KPI: fill rate, backlog days, inventory turns, capacity util, cost variance, service level, on_time_rate。
  - 保管期間: Planバージョン18か月、KPI24か月、監査36か月（仮）。
- [x] T0-3: 非機能要件（性能、容量、ロック戦略、監査）を想定仕様として整理。
  - 性能: `POST /plans/integrated/run` P95 3分、集計API P95 1.5秒。
  - 容量: Planあたり最大500万行を想定し、`PLANS_DB_MAX_ROWS`（600）で古いversionをアーカイブ。
  - ロック/監査: 行ロック、イベント種別（edit/lock/unlock/submit/approve/reconcile/rollback/export）、Slack通知を仮定。
  - 詳細は `docs/plan_db_assumed_requirements.md` に記載。

### P1: スキーマ設計・Alembic
- [x] T1-1: `plan_series` 指標セットと粒度（時間/品目/ロケーションキー）の定義。`docs/AGG_DET_RECONCILIATION_JA.md` と整合。
  - 現状成果物: `aggregate.json`（family×period）, `sku_week.json`（sku×week）, `plan_final.json`（weekly_summary + boundary_summary）, `mrp.json`（SKU×週の供給/在庫/発注）。UIは `app/ui_plans.py:600-642` で行単位を表示し、`schedule.csv`/`compare.csv` などCSVへ投影。
  - ディメンション: `version_id`(TEXT FK), `level`(`aggregate|det|mrp|agg_summary`), `time_bucket_type`(`week|month`), `time_bucket_key`(TEXT; ISO週 or YYYY-MM), `item_key`(TEXT; family/sku), `location_key`(TEXT; site/region/network), `scenario_id`(INTEGER; nullable), `config_version_id`(INTEGER; nullable)。
  - 指標列: `demand`, `supply`, `backlog`, `inventory_open`, `inventory_close`, `prod_qty`, `ship_qty`, `capacity_used`, `cost_total`, `service_level`, `spill_in`, `spill_out`, `adjustment`, `carryover_in`, `carryover_out`。FLOAT nullable、0初期化を基本。
  - メタ列: `source`(TEXT; aggregate/allocate/mrp/reconcile/override), `policy`(TEXT; anchor/roundingなど), `cutover_flag`(BOOLEAN), `boundary_zone`(TEXT; pre/at/post), `window_index`(INTEGER), `lock_flag`(BOOLEAN), `locked_by`(TEXT), `quality_flag`(TEXT), `created_at`(INTEGER; ms epoch)。
  - 主キー: `(version_id, level, time_bucket_type, time_bucket_key, item_key, location_key)`。
  - インデックス: `(version_id, level, item_key)`, `(version_id, level, time_bucket_type, time_bucket_key)`, `(level, time_bucket_type, time_bucket_key)`, `(version_id, cutover_flag)`。
  - `docs/plan_db_assumed_requirements.md` に準拠し、日次粒度は対象外。拠点はsite/region/networkの階層表示を想定。
- [x] T1-2: `plan_overrides` / `plan_kpis` / `plan_jobs` の列構成とインデックス方針を決定し、ER図を `docs/` に追加。
  - `plan_overrides`:
    - テーブル: `plan_overrides`（ロック・編集内容）と `plan_override_events`（監査イベント）に分割。
    - `plan_overrides` 列: `id`(INTEGER PK AUTOINCREMENT), `version_id`(TEXT FK), `level`(`aggregate|det`), `key_hash`(TEXT), `payload_json`(TEXT), `lock_flag`(BOOLEAN), `weight`(FLOAT nullable), `author`(TEXT), `source`(TEXT; ui/api/cli/cli-batch), `created_at`(INTEGER), `updated_at`(INTEGER)。ユニーク制約 `(version_id, level, key_hash)`。
    - `plan_override_events` 列: `id` PK, `override_id`(INTEGER FK→plan_overrides.id ON DELETE CASCADE), `version_id`, `level`, `key_hash`, `event_type`(`edit|lock|unlock|submit|approve|reconcile|rollback|export`), `event_ts`(INTEGER), `payload_json`(TEXT), `actor`(TEXT), `notes`(TEXT)。インデックス `(version_id, event_ts DESC)`, `(override_id, event_ts DESC)`。
    - ロック/重みは `plan_overrides` に最新値を保持し、イベント履歴は `plan_override_events` で参照。

  - `plan_kpis`:
    - 列: `version_id`(TEXT FK), `metric`(TEXT), `bucket_type`(`total|week|month|family|sku|site|region`), `bucket_key`(TEXT), `value`(FLOAT), `unit`(TEXT), `dimension_filters`(TEXT; JSON), `source`(TEXT; aggregate/det/report/run_compare), `run_id`(TEXT FK→runs.run_id, nullable), `created_at`(INTEGER), `updated_at`(INTEGER)。主キー `(version_id, metric, bucket_type, bucket_key)`。
    - インデックス: `(metric, bucket_type, bucket_key)`, `(run_id)`, `(version_id, bucket_type)`。
    - 想定KPIラベルは `docs/plan_db_assumed_requirements.md` に準拠。

  - `plan_jobs`:
    - 列: `job_id`(TEXT PK, FK→jobs.job_id), `version_id`(TEXT FK), `config_version_id`(INTEGER), `scenario_id`(INTEGER), `status`(TEXT), `run_id`(TEXT FK→runs.run_id, nullable), `trigger`(TEXT; ui/api/cli/scheduled), `submitted_at`(INTEGER), `started_at`(INTEGER), `finished_at`(INTEGER), `duration_ms`(INTEGER), `retry_count`(INTEGER), `error`(TEXT), `payload_json`(TEXT)।
    - インデックス: `(version_id)`, `(config_version_id)`, `(run_id)`, `(status, submitted_at DESC)`, `(trigger, submitted_at DESC)`。
    - `jobs` テーブルからPlan関連のみを抽出し、RunRegistryとの紐付けとステータス確認を容易にする。

  - ER図タスク: `plan_series` と上記3テーブル、`plan_versions`・`plan_artifacts`・`runs` の関係をMermaid/PlantUMLで描画。主なリレーション: `plan_jobs.version_id -> plan_versions.version_id`, `plan_kpis.version_id -> plan_versions.version_id`, `plan_overrides.version_id -> plan_versions.version_id`, `plan_jobs.run_id -> runs.run_id`。
- [x] T1-3: Alembicマイグレーション実装（作成・ロールバック・サンプルシード）。
  - 新規テーブル: `plan_series`, `plan_overrides`, `plan_override_events`, `plan_kpis`, `plan_jobs`。既存 `plan_versions`, `plan_artifacts`, `runs`, `jobs` と外部キーで連携。
  - DDL詳細:
    - `plan_series`: 主キー `(version_id, level, time_bucket_type, time_bucket_key, item_key, location_key)`、外部キー `version_id`→`plan_versions.version_id` (ON DELETE CASCADE)。指標列・メタ列はT1-1で定義済。インデックス `(version_id, level, item_key)`, `(version_id, level, time_bucket_type, time_bucket_key)`, `(level, time_bucket_type, time_bucket_key)`, `(version_id, cutover_flag)`。
    - `plan_overrides`: PK `id` AUTOINCREMENT。外部キー `version_id`→`plan_versions`。ユニーク `(version_id, level, key_hash)`。インデックス `(version_id, level)`, `(version_id, lock_flag)`。
    - `plan_override_events`: PK `id`。FK `override_id`→`plan_overrides.id` (CASCADE)、`version_id`→`plan_versions`。インデックス `(version_id, event_ts DESC)`, `(override_id, event_ts DESC)`。
    - `plan_kpis`: 主キー `(version_id, metric, bucket_type, bucket_key)`。FK `run_id`→`runs.run_id` (SET NULL)。インデックス `(metric, bucket_type, bucket_key)`, `(run_id)`, `(version_id, bucket_type)`。
    - `plan_jobs`: PK/FK `job_id`→`jobs.job_id` (CASCADE)。インデックス `(version_id)`, `(config_version_id)`, `(run_id)`, `(status, submitted_at DESC)`, `(trigger, submitted_at DESC)`。
  - Alembic実装方針: `alembic revision -m "add plan db tables"` を作成し、`inspect(bind).has_table` 判定で冪等性を確保。SQLite制約に配慮し `server_default` はTEXT/NUMERIC/整数のみ採用。
  - ダウングレード: 各テーブルのインデックスをdrop後、テーブルをdrop。`plan_jobs` は既存 `jobs` テーブルへ影響しないが、データ喪失注意コメントを残す。
  - サンプルデータ: Alembicでは投入せず、T2-1 以降で `scripts/seed_plan_db.py` を整備予定。
  - 検証手順: 上記マイグレーション手順案(1)-(6)に従い、upgrade/downgradeとCIスモークを実施。
- [x] T1-4: `mypy` / `sqlalchemy` 型定義の更新と`core/config`連携確認。
  - PlanRepositoryインターフェース:
    - ファイル: `core/plan_repository.py` を新設。`PlanSeriesRow`, `PlanOverride`, `PlanOverrideEvent`, `PlanKpiRow`, `PlanJobRow` を `TypedDict` または `pydantic.BaseModel` で定義。
    - メソッド案:
      - `insert_plan_series(rows: Iterable[PlanSeriesRow]) -> None`
      - `fetch_plan_series(version_id: str, level: str, *, bucket_type: str | None = None, bucket_key: str | None = None) -> list[PlanSeriesRow]`
      - `upsert_plan_override(override: PlanOverride) -> None`
      - `insert_plan_override_events(events: Iterable[PlanOverrideEvent]) -> None`
      - `fetch_plan_overrides(version_id: str, level: str) -> list[PlanOverride]`
      - `insert_plan_kpis(rows: Iterable[PlanKpiRow]) -> None`
      - `fetch_plan_kpis(version_id: str, metric: str | None = None) -> list[PlanKpiRow]`
      - `upsert_plan_job(job: PlanJobRow) -> None`
      - `fetch_plan_jobs(version_id: str | None = None, status: str | None = None) -> list[PlanJobRow]`
    - 低レベル実装は `app/db.py` に配置し、PlanRepositoryから呼び出す。
  - 型定義方針:
    - `typing.TypedDict` で必要なキーを明示しつつ、`pydantic` モデルを用いて入力検証を行う。
    - `mypy.ini` は現状 `ignore_missing_imports=True` のため、新規モジュールに対し `py.typed` を配置し局所的に型チェックを強化。
    - `typing.Protocol` で PlanRepository のインターフェースを定義し、テスト時にモック実装を差し替え可能にする。
  - `core/config` 連携:
    - `prepare_canonical_inputs` の戻り値に `CanonicalInputBundle` 的なTypedDictを導入し、`plan_series` 保存時に `config_version_id` を必須チェック。
    - `core/config/storage` に変更は不要だが、Plan保存時に `canonical_config_storage.exists(config_version_id)` を呼び出すヘルパを追加。
  - mypy/CI対応:
    - `plan_repository` モジュールで `mypy --strict` を試験運用、必要に応じて `type: ignore` を最小限で使用。
    - CIジョブ例: `PYTHONPATH=. mypy core/plan_repository.py app/db.py`。
    - `tests/test_plans_persistence.py`（T2-4で追加予定）がTypedDictを利用するため、ユニットテストでも型整合を検証。
  - ドキュメント: `docs/plan_db_assumed_requirements.md` に基づき、PlanRepository内でのハードコード値（KPIリスト、イベント種別）を定数モジュールにまとめる。

### P2: 永続化レイヤ実装
- [ ] T2-1: `core/plan_repository.PlanRepository`（仮）を実装し、トランザクション制御・バルクインサート・ロールバックAPIを提供。
  - 実装概要:
    - エントリポイント: `core/plan_repository.py` にクラス `PlanRepository` を実装し、`__init__(self, conn_factory: Callable[[], sqlite3.Connection])` で接続供給。
    - 主要API（型はT1-4参照）:
      - `write_plan(version_id: str, *, series: Iterable[PlanSeriesRow], overrides: Iterable[PlanOverride], override_events: Iterable[PlanOverrideEvent], kpis: Iterable[PlanKpiRow], job: PlanJobRow | None) -> None`
      - `fetch_plan_series(...)`, `fetch_plan_overrides(...)`, `fetch_plan_kpis(...)`, `fetch_plan_jobs(...)`, `delete_plan(version_id: str)`。
    - 書込み手順: 1) `BEGIN IMMEDIATE` で排他取得 → 2) 対象versionの既存行を削除（`plan_series` 等） → 3) `executemany` でバルク挿入（バッチサイズ 5,000 行） → 4) ジョブ/イベント/KPI挿入 → 5) `COMMIT`。
    - エラー時は `ROLLBACK` 後、`PlanRepositoryError` をraise。SQLite例外は `sqlite3.Error` をラップ。
  - トランザクション/ロック戦略:
    - `with self._conn() as conn:` で自動コミット制御。WALモードを推奨（将来PostgreSQL移行を視野）。
    - `PRAGMA foreign_keys = ON` を毎接続で設定。
    - 大量挿入時は `cursor.executemany` によるリトライ（1回）を実装。失敗時はログ出力して例外。
  - 検証計画:
    - スモーク: `PlanRepository.write_plan()` → `fetch_plan_series()` → データ整合を確認。
    - 例外: 外部キー違反（存在しない `version_id`）で `PlanRepositoryError` が投げられることをテスト。
    - パフォーマンス: 5M行を想定し、バッチサイズとコミット頻度を調整（初期値 50,000 / commit 1回）。
  - 既存コード連携:
    - `app/plans_api.py` と `app/jobs.py` からPlanRepositoryを呼び出し、`db.upsert_plan_artifact` は互換用途に限定。
    - CLIスクリプトは `scripts/_plan_repository_utils.py`（仮）を経由し、ファイル出力とDB保存を両立させる。
  - 未決: テスト用のインメモリ接続（`:memory:`）をサポートするか要判断。
- [ ] T2-2: 既存 `scripts/plan_*.py` をリファクタし、計算結果を `PlanRepository` 経由で保存できるよう抽象化。
  - 対象スクリプト: `plan_aggregate.py`, `allocate.py`, `mrp.py`, `reconcile.py`, `reconcile_levels.py`, `anchor_adjust.py`, `export_reconcile_csv.py`, `report.py`, `run_planning_pipeline.sh`。
  - 方針:
    1. スクリプト本体からファイルI/Oロジックを分離し、共通モジュール `scripts/plan_pipeline_io.py`（仮）に集約。
    2. `PlanRepository` と `LocalArtifactsWriter` の2系統を切り替え可能にする（`--storage=db|files|both`）。既定は `both`（互換性確保）。
    3. 集計結果はPythonオブジェクト（dict/list）で返し、呼び出し側でPlanRepositoryへ渡す。CLI単体実行時は従来通りJSON/CSVを生成。
    4. `run_planning_pipeline.sh` は `python scripts/run_planning_pipeline.py`（新規統合CLI）へ移行し、オプションでDB書込みを有効化。
  - 実装ステップ案:
    - Step1: 各スクリプトのmain関数を `compute_*`（純粋関数）と `cli_main`（入出力処理）に分解。
    - Step2: `scripts/plan_pipeline_io.py` で PlanRepository への書込みユーティリティを実装。`PlanRunContext`（config_version_id, version_id 等）を受け取る。
    - Step3: `app/plans_api.py` と `app/jobs.py` で新APIを呼び出し、`storage=db|files` を選択可能にする。
    - Step4: 既存テストを更新し、DBモード/ファイルモード双方で検証。
  - CLI互換性: 既存コマンドライン引数を保持しつつ、`--no-files` や `--no-db` を追加。従来のJSON成果物は `PlanRepository` からエクスポート可能。
  - 影響範囲: `scripts/run_planning_pipeline.sh` は段階的に廃止予定（README更新が必要）。
- [ ] T2-3: `app/jobs.prepare_canonical_inputs` / `app/plans_api.py` を直接DB書込みに切替（tempディレクトリは互換用途のみ保持）。
  - 方針:
    - `prepare_canonical_inputs` は従来通り一時ディレクトリを返しつつ、PlanRepositoryへ渡すための構造化データ（Aggregate/DET/MRP結果）を返却する。
    - `app/plans_api.py::post_plans_integrated_run` と `app/jobs::_run_planning_pipeline` は、ストレージモードを `storage_mode = os.getenv("PLAN_STORAGE_MODE", "both")` などで切替可能にする。
    - ファイル出力はオプション化（互換用）。`out_dir` が指定された場合のみJSON/CSVを生成し、PlanRepositoryへの書込みは常時行う。
  - 実装ステップ案:
    1. PlanRepositoryをDI（依存性注入）で受け取れるよう `app/__init__.py` で初期化。
    2. `post_plans_integrated_run` で計算ステップ結果を受け取り、`PlanRepository.write_plan(...)` を呼び出す。
    3. `app/jobs.py::_run_planning_pipeline` でも同様にPlanRepositoryへ書込み、ジョブ結果`result_json` にはDB保存情報を追加（`storage="db"` フラグ等）。
    4. 旧 `db.upsert_plan_artifact` の呼び出しは段階的に削除（互換期間中は `storage_mode in {"files", "both"}` の場合のみ実行）。
  - 注意点:
    - PlanRepository書込み失敗時は例外をRaiseし、APIレスポンス/ジョブステータスにエラーを設定。
    - `PlanRepository` 呼び出し後にRunRegistry連携 (`record_canonical_run`) を実行し、`plan_jobs` の run_id を更新。
    - `PlanRepository` への書込み後、必要に応じ `PlanRepository.delete_plan(version_id)` で再実行時にクリーンアップ。
- [ ] T2-4: ユニットテストを追加（Aggregate/Detail/Overridesの読み書き、トランザクション失敗時のロールバック確認）。
  - テストスイート: `tests/test_plan_repository.py`（新規）。pytest + sqlite一時ファイルを使用。
  - 主要ケース:
    1. `write_plan` → `fetch_plan_series`/`fetch_plan_overrides`/`fetch_plan_kpis` が正しくデータを返す。
    2. `write_plan` で同一version再実行時に既存データが削除され、新データで置換される。
    3. 外部キー違反（不存在version_id/config_version_id）で `PlanRepositoryError` が発生し、トランザクションがロールバックされる。
    4. ロックフラグ/イベントが正しく保存され、`fetch_plan_overrides` が最新情報を返す。
    5. `delete_plan` が関連テーブルの行をCASCADE削除する。
    6. 大量挿入（例: 10万行）でバッチ挿入が成功し、パフォーマンスが許容範囲。
  - 補助ユーティリティ: `tests/util_plan_db.py` を作成し、テンポラリDBの初期化（Alembic適用）を共通化。
  - CI: `pytest tests/test_plan_repository.py -k "not slow"` を通常ジョブに組込み。大量挿入テストは `@pytest.mark.slow` で別ジョブに分離。

### P3: UI/API/RunRegistry連携
- [ ] T3-1: `/plans` APIレスポンスを新DB構造に合わせて更新（ページング・フィルタ・サマリ項目追加）。
  - 目的: Plan一覧/APIレスポンスで `plan_series` / `plan_kpis` の要約値を提供し、UIで即時集計を表示できるようにする。
  - 変更点:
    - エンドポイント: `GET /plans` にクエリパラメータ `include=summary,kpi` を追加。既定は `summary`。
    - レスポンス項目例: `{version_id, status, cutover_date, summary: {agg_rows, det_rows, kpi: {fill_rate, backlog_days, inventory_turns}, last_updated_at}, jobs: {last_job_id, status}}`。
    - データ取得: `PlanRepository.fetch_plan_kpis()` と `PlanRepository.fetch_plan_series()` を内部で呼び出し、必要な指標だけを集計。大規模Planでは `LIMIT` を設定し、`total_rows` を返す。
    - ページング: `GET /plans` は既存の `offset/limit` を維持しつつ、`order_by=created_at|version_id` を追加。
  - 実装ステップ案:
    1. バックエンド: `app/plans_api.py::get_plans` をPlanRepositoryベースにリファクタ。`db.list_plan_versions` から `PlanRepository` / `db` コンボへ。
    2. `PlanSummaryAssembler`（新規ヘルパ）を作成し、PlanRepositoryから取得したデータを整形。
    3. UI (`app/ui_plans.py`) で新サマリを利用し、従来のJSON blob依存部分を削除。
    4. テスト: `/plans` APIのレスポンススナップショットを更新し、kpi/summaryが返却されることを確認。
  - 後方互換性: `include=legacy` を指定した場合、従来の`plan_artifacts`ベースレスポンスを返す期間を設ける（デフォルトは新形式）。
- [ ] T3-2: `/ui/plans` 表示・編集画面を `plan_series` / `plan_overrides` 読込に置換し、JSON blob依存を削除。
  - UI構成:
    - Overviewタブ: `PlanRepository.fetch_plan_series(..., level="aggregate")` の要約と `plan_kpis` を表示。
    - Aggregateタブ: `plan_series` のaggregate行をテーブル表示（ページング）。現行の `plan_artifact` 読込を置換。
    - Detailタブ: `plan_series` level="det" で詳細行を取得し、PlanRepository由来データ＋ overrides を適用した結果を表示。
    - Edit/Lock操作: `plan_overrides`／`plan_override_events` を直接編集し、APIで即時反映。従来の JSON blob 書込みを廃止。
  - 実装ステップ案:
    1. `app/ui_plans.py` で `db.get_plan_artifact` 呼び出しを `PlanRepository` ベースへ置換。
    2. テーブル描画を `PlanSeriesViewModel`（新規）を通じて行い、レベルごとにカラム定義をマッピング。
    3. 編集フォーム（`/plans/{version}/psi` API呼び出し）はPlanRepository経由の更新結果を即時反映（レスポンスに最新の行を返す）。
    4. ロックアイコンは `plan_overrides.lock_flag` ベースで表示し、PlanRepositoryへの更新成功後に再描画。
    5. CSVエクスポートは PlanRepository → ファイル生成へ切り替え。
  - UX改善: 画面読み込み時のレスポンスを改善するため、初回は集約表示のみ（詳細はlazyロード）。
  - 過渡期: `?legacy=1` で旧表示にフォールバックできるよう暫定対応。
- [ ] T3-3: RunRegistry記録 (`record_canonical_run`) に `plan_job_id` と `plan_series` リンクを追加。Run詳細からPlanへのドリルダウン（集計/詳細ビュー）を実装。
  - 目的: Run履歴UI/APIでPlan詳細へ即座に遷移できるよう、PlanRepositoryのデータとRunRegistryを双方向リンク。
  - 方針:
    - `record_canonical_run` で `plan_job_id`（PlanRepositoryに書き込んだジョブID）を `runs` テーブルへ保存。
    - Run詳細API `/runs/{run_id}` に `plan_version_id`, `plan_job_id`, `plan_kpi_summary` を追加。
    - `/ui/runs` でPlanリンクを表示し、クリックで `/ui/plans/{version_id}?include=run:{run_id}` を開く。
    - Plan側では `plan_jobs.run_id` を利用してRun結果タブにRun詳細を表示（Plan→Run逆リンク）。
  - 実装ステップ案:
    1. `app/run_registry.py::record_canonical_run` を拡張し、`PlanRepository` から取得した `PlanJobRow` をrun保存時に併せて書き込む。
    2. Run詳細API/テンプレートを更新し、Planサマリ（主要KPI・version情報）を表示。
    3. Plan UI のResultsタブでRun情報を`PlanRepository` ではなくRunRegistryから参照し、差分/比較を容易にする。
    4. テスト: `/runs` API・UIでPlanリンクが表示され、双方向遷移が機能することを検証。
  - 後方互換: `plan_job_id` 未設定のRun（旧データ）は従来通り動作。
- [ ] T3-4: メトリクス導入（`PLAN_SERIES_ROWS_TOTAL`, `PLAN_DB_WRITE_LATENCY`）とPrometheusエクスポートの追加。
  - 目的: PlanRepository運用状況を監視し、書込み失敗・遅延・容量増を早期検知。
  - メトリクス案:
    - Counter `plan_db_write_total`：PlanRepository書込み成功件数（labels: storage_mode）。
    - Counter `plan_db_write_error_total`：書込み失敗件数（labels: error_type）。
    - Histogram `plan_db_write_latency_seconds`：write_plan処理時間。Buckets: [0.5, 1, 2, 5, 10]。
    - Gauge `plan_series_rows_total`：PlanRepository書込み時の行数を最新値で保持。
    - Gauge `plan_db_size_bytes`：`data/scpln.db` ファイルサイズを定期取得（バックアップジョブで更新）。
    - Gauge `plan_db_last_success_timestamp`：直近成功書込みのUNIXタイム。
  - 実装案:
    - `app/metrics.py` に新メトリクス定義。PlanRepository書込み完了時に更新。
    - `scripts/run_planning_pipeline` 実行後にもPlanRepository経由でメトリクスを更新（storage_mode一致確認）。
    - `/metrics` エンドポイントに新メトリクスが露出することを確認。
  - 監視設定:
    - Alert1: `plan_db_write_error_total` が5分で>0 → PagerDuty。
    - Alert2: `plan_db_write_latency_seconds{quantile="0.95"} > 5` for 10分 → Slack警告。
    - Dashboard: Plan書込み件数、失敗率、DBサイズ推移。

### P4: CLI・運用整備
- [ ] T4-1: `scripts/plan_export.py`（新規）を実装し、DB→JSON/CSVエクスポートを標準化。
- [ ] T4-2: 既存Runbook (`docs/TUTORIAL-JA.md`, `docs/run_registry_operations.md`) をPlan DB永続化前提へ更新。
- [ ] T4-3: 運用向けメンテスクリプト（バックアップ、アーカイブ、トリミング）を `scripts/plan_db_maint.py` として提供。

### P5: 移行・検証・リリース
- [ ] T5-1: 既存 `plan_artifacts` JSON から新テーブルへコピーするバックフィルスクリプトを実装（Dry-runモード付き）。
- [ ] T5-2: `tests/test_plans_*` を新DB構造で動作するよう更新し、CIに `PlanRepository` 経路の統合テストを追加。
- [ ] T5-3: Dev→Staging→Production の段階移行チェックリストを作成（DBバックアップ、Alembic実行、Smokeテスト、監視確認）。
- [ ] T5-4: カットオーバー時のロールバック手順（旧`plan_artifacts`へのフォールバック、RunRegistry影響）をRunbook化。

## 6. リスクと対応策
- データ量肥大: `plan_series` はレベル×期間×SKUで膨大になるため、週次で `version_id` 単位の圧縮・削除ポリシーを導入。`RUNS_DB_MAX_ROWS` 相当の `PLANS_DB_MAX_ROWS` を環境変数で設定できるようにする。
- 同時編集競合: UI編集は `plan_overrides` に行ロック情報を保持し、APIでバージョン・タイムスタンプチェックを実装。悲観/楽観どちらを採用するかP0で決定。
- 後方互換: 既存JSON APIを即時廃止せず、`?legacy=1` フラグで旧構造を返す期間を設け、依存サービスの移行計画を共有。
- マイグレーション失敗: Alembic実行前に `data/scpln.db` のバックアップを取得し、`alembic downgrade` 手順と検知アラートを整備。

## 7. 未決事項・意思決定保留
- `plan_series` の粒度: `day` と `week` を同一テーブルで扱うか、テーブル分割するか要検討。
- KPI保管期間: 全履歴保存か、主要バージョンのみを保持するか。業務チームとの擦り合わせ待ち。
- 監査ログの詳細度: UI操作ごとに差分スナップショットを保持するか、フィールド単位にするか判断が必要。

## 8. 検証・監視計画
- ユニットテスト: `tests/test_plans_persistence.py`（新規）でCRUDと集計APIを検証。
- 統合テスト: `make smoke-plan-run` をPlan DB経路に更新し、Aggregate/Detail反映とRunRegistry連携を確認。
- 監視: Prometheusメトリクスに `plan_db_write_latency_seconds`, `plan_series_rows_total`, `plan_db_errors_total` を追加し、Grafanaダッシュボードを更新。
- バックアップ: `scripts/backup_plan_db.py` を作成し、RunRegistryバックアップと同じスケジュールで日次取得。

## 9. リリース計画
1. DevでAlembic適用→バックフィル→Smokeテスト。
2. Stagingで負荷テスト（代表Plan 3件、過去版20件）とUI手動検証。
3. 本番切替は低負荷帯（夜間）に実施。切替時はPlan作成APIを一時停止し、バックフィル完了後に再開。
4. 切替後7日間は旧`plan_artifacts` を同期維持し、問題発生時にロールバック可能な状態を保持。

## 10. 更新履歴
- 2025-10-05: 初稿作成（Codex）。
- 2025-10-05: ブランチ戦略・実装フェーズ準備を追記。
