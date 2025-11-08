# Planning入力可視化・正規化 改修仕様書

## 目的
- `samples/planning/*.csv` 依存を廃止し、計画生成に使う入力を Canonical version に紐付く `planning_input_sets` として正規管理する。
- UI/API/CLI すべてから入力セットを参照・選択・追跡できる状態を段階的に整備する。
- タスク進捗（特に GenAI エージェント作業）を本ドキュメントで共有し、施策/ログ/残タスクを一元管理する。

## 背景と課題
- `PlanningRunParams.input_dir` が `samples/planning` を暗黙参照し、UI から入力内容が見えない。
- `planning_calendar.json` や配賦パラメータなど、計画に不可欠な設定がファイルに散在し、Canonical設定と連動しない。
- サンプルCSVが本番計画でも流用され、どのデータで実行したか追跡できない。

## ゴール
- Run/Plan が参照した入力セットを `config_version_id` + `label` で追跡できる。
- UI に「Planning Inputs」表示/選択を追加し、CLI では Import/Export が `planning_input_sets` を操作する。
- README/TUTORIAL (英/日) に統一手順を記載し、ユーザーが CLI と UI を行き来できるようにする。

## 非ゴール
- PSI/計画アルゴリズム自体の変更。
- サンプルデータの大幅刷新（本設計書では扱わない）。

## 前提
- `core/config/models` の拡張、および `core/config/storage` の CRUD を実装済み。
- Alembic migration `36858d371b14_add_planning_input_sets.py` が適用されていること。

## フェーズ
1. **Phase 0**: モデル・DB・CLI 基盤整備（完了済み）
2. **Phase 1**: Planning Hub / API で InputSet を選択・適用できるようにする（進行中）
3. **Phase 2**: UI で入力セットの閲覧・アップロード承認フローを提供
4. **Phase 3**: レガシー CSV モードの廃止・監査強化・テスト資産更新

## タスク一覧
| ID | フェーズ | 内容 | 担当 | 状態 | 備考 |
|----|----------|------|------|------|------|
| T0-1 | P0 | PlanningInputSet モデル/CRUD/Alembic 整備 | agent | 完了 | models/storage/migration |
| T0-2 | P0 | Import/Export CLI 実装 | agent | 完了 | `scripts/import/export_planning_inputs.py` |
| T0-3 | P0 | README/TUTORIAL (英/日) に CLI 手順追記 | agent | 完了 | 本ドキュメント含む |
| T1-1 | P1 | PlanningRunParams に `input_set_label` を追加し API/UI へ伝播 | agent | 完了 | |
| T1-2 | P1 | Planning Hub で InputSet を選択可能にする UI 変更 | agent | 完了 | `plans.html` フォーム＋Plan/Run detail カード |
| T1-3 | P1 | Run/Plan DBテーブルに InputSet ラベルを永続化 | agent | 完了 | `runs.input_set_label`, `plan_versions.input_set_label` |
| T1-4 | P1 | InputSetカードに Diff/Export CTA を追加 | agent | 完了 | UI, API, templates |
| T2-1 | P2 | Planning Inputs タブ実装（閲覧・差分） | TBD | 未着手 | app/ui_plans.py |
| T2-2 | P2 | CSVアップロード→検証→承認ウィザード | TBD | 未着手 | UI + storage |
| T3-1 | P3 | Legacy CSV モードの停止と警告 | agent | 完了 | ログとPrometheusメトリクスで検知 |
| T3-2 | P3 | テスト資産を InputSet ベースに切り替え | TBD | 未着手 | tests/* |

## CSV→Canonical 差分（要約）
| CSV/JSON | ギャップ | 対応方針 |
|----------|----------|----------|
| demand_family.csv | family粒度が Canonical に保存されない | `PlanningFamilyDemand` で period別合計を記録 |
| capacity.csv | resource_type/calendar が欠落 | `PlanningCapacityBucket` に resource_type/calendar_code を追加 |
| mix_share.csv | 履歴・期間情報なし | `PlanningMixShare` で effective_from/to・weight_source を保持 |
| inventory.csv | loc/item以外のポリシー情報欠落 | `PlanningInventorySnapshot` に reorder/order_up_to 等を登録 |
| open_po.csv | source/dest/参照ID不明 | `PlanningInboundOrder` でノードとIDを保存 |
| planning_calendar.json | Canonical割り当てが曖昧 | `PlanningCalendarSpec` として InputSet に紐付け |
| period_cost/score.csv | 指標メタ・単位無し | `PlanningPeriodMetric` に unit/source/metric_code を導入 |

## モデル定義（抜粋）
- `PlanningInputSet`: `config_version_id`, `label`, `status (draft|ready|archived)`, `source (csv|ui|api|seed)`, `calendar_spec`, `planning_params`, `aggregates`.
- サブモデル: `PlanningFamilyDemand`, `PlanningCapacityBucket`, `PlanningMixShare`, `PlanningInventorySnapshot`, `PlanningInboundOrder`, `PlanningPeriodMetric`, `PlanningInputAggregates`.

## CLI仕様
### Import (`scripts/import_planning_inputs.py`)
- 主要引数: `-i/--input-dir`, `--version-id` or `--new-version-id`, `--label`, `--apply-mode merge|replace`, `--validate-only`, `--json`.
- 処理: CSV/JSONを読み込み→Pydantic変換→`create_planning_input_set` or `update_planning_input_set`。
- 代表コマンド:
  ```bash
  PYTHONPATH=. python scripts/import_planning_inputs.py \
    -i samples/planning \
    --version-id 14 \
    --label demo_inputs \
    --apply-mode replace
  ```

### Export (`scripts/export_planning_inputs.py`)
- 主要引数: `--label` or `--version-id`, `-o/--output-dir`, `--include-meta`, `--diff-against`, `--zip`, `--json`.
- 出力: `demand_family.csv` などの CSV、および `planning_calendar.json`。`--zip` 指定でアーカイブ化。
- 代表コマンド:
  ```bash
  PYTHONPATH=. python scripts/export_planning_inputs.py \
    --label demo_inputs --include-meta --zip --json
  ```

## DBスキーマ & Alembic
- 親: `planning_input_sets (id, config_version_id, label, status, source, metadata_json, calendar_spec_json, planning_params_json, created_at, updated_at)`.
- 子: `planning_family_demands`, `planning_capacity_buckets`, `planning_mix_shares`, `planning_inventory_snapshots`, `planning_inbound_orders`, `planning_period_metrics`（いずれも `input_set_id` FK, ON DELETE CASCADE）。
- Migration `36858d371b14_add_planning_input_sets.py`:
  - テーブル作成 + インデックス。
  - `canonical_config_versions.metadata_json` 内 `planning_payload` を走査し、InputSet とサブテーブルへシード。
  - ダウングレード時は InputSet を `planning_payload` へ戻す。
- Migration `8eeb7b69d3b6_add_input_set_label_to_plans_and_runs.py`:
  - `runs` テーブルと `plan_versions` テーブルに `input_set_label` カラム（nullable, index付き）を追加。

## Storage API
- 新規公開関数: `create_planning_input_set`, `update_planning_input_set`, `get_planning_input_set`, `list_planning_input_sets`, `delete_planning_input_set`.
- 例外: `PlanningInputSetNotFoundError`, `PlanningInputSetConflictError`.
- サブテーブルは `_replace_planning_aggregates` が全削除→一括挿入を担当。

## 進捗ログ
- `2025-11-08 / agent / P0 / T0-1 / PlanningInputSet モデルとCRUDを実装`
- `2025-11-08 / agent / P0 / T0-2 / Import/Export CLI を実装し README/TUTORIAL に反映`
- `2025-11-08 / agent / P0 / Docs / README・README_JA・TUTORIAL系に Import/Export 手順を追記`
- `2025-11-08 / agent / P1 / T1-1 / PlanningRunParams / runs_api / plans_api / jobs に input_set_label を導入し、API・ジョブ・計画実行が指定InputSetを利用できるよう実装`
- `2025-11-08 / agent / P1 / T1-2 / Planning Hub フォームに InputSet セレクタと ready set API（/ui/plans/input_sets）を追加`
- `2025-11-08 / agent / P1 / T1-2 / Plan detail（plans_detail.html）に InputSet カードを追加し、storage/artifact 情報とエクスポート手順を表示`
- `2025-11-08 / agent / P1 / T1-2 / Run detail（run_detail.html）に InputSet カードを追加し、RunRegistry summaryからのラベルと Plan artifact を統合表示`
- `2025-11-08 / agent / P1 / T1-2 / Plan・Run 一覧に InputSet 列とフィルタを追加し、/runs?input_set_label クエリと UI フィルタを実装`
- `2025-11-08 / agent / P1 / T1-2 / Plan一覧にサーバーサイドの input_set_label クエリフィルタを追加（/ui/plans?input_set_label=...）`
- `2025-11-09 / agent / P1 / T1-3 / DBマイグレーション(8eeb7b69d3b6)を追加し、plan_versionsとrunsテーブルにinput_set_labelカラムを導入`
- `2025-11-09 / agent / P1 / T1-3 / app/db.py を修正し、plan_versions 関連のCRUDがinput_set_labelを永続化・取得できるように変更`
- `2025-11-09 / agent / P1 / T1-3 / app/run_registry_db.py を修正し、Runの記録・取得時にinput_set_labelをDBカラム経由で処理するように正規化`
- `2025-11-09 / agent / P1 / T1-4 / Plan/Run詳細カードにExport(Zip)およびDiffボタンを追加`
- `2025-11-09 / agent / P1 / T1-4 / InputSetをzipエクスポートするAPIエンドポイント(/api/plans/input_sets/{label}/export)を実装`
- `2025-11-09 / agent / P1 / T1-4 / InputSet差分表示UI(/ui/plans/input_sets/{label}/diff)とテンプレートを実装`
- `2025-11-09 / agent / P3 / T3-1 / Legacyモード実行を検知し、WARNINGログとPrometheusカウンター(scpln_legacy_mode_runs_total)で記録する監視ロジックを実装`

## Phase 0 詳細アクション（完了）
1. CSV→Canonical差分表を整理（本書「CSV→Canonical差分」参照）。
2. PlanningInputSet とサブモデルの Pydantic 定義を `core/config/models` へ追加。
3. Storage API と Alembic migration を実装し、Import/Export CLI から利用。

## Phase 1 TODO
- ~~Planning Hub UI（/ui/plans, /ui/runs）で InputSet 表示/操作を拡充（一覧フィルタ・カードは完了、Diff/Export CTA と警告フローを残す）。~~ (完了)
- ~~RunRegistry / plan detail に InputSet 情報（label, id, diffリンク）を表示し、履歴比較に利用できるようにする（Run detail のCTA強化、Plan detail のDiffリンク連携）。~~ (完了)
- ~~Run/Plan API レスポンスや `plan_versions` メタへ InputSet 情報を永続化し、再実行系フローで再利用する。~~（完了）

## Phase 1 詳細仕様: InputSetラベル伝播と可視化

### 1. パラメータ定義と正規化
- `PlanningRunParams`（`app/simulation_api.py`）に `input_set_label: Optional[str]` を追加済み。FastAPI バリデータで空文字を `None` に正規化し、UI/API/CLI のいずれから渡っても一貫した値になるようにする。
- `/runs` エンドポイントでは `options.input_set_label` を `str | None` として受け取り、`_as_str` でトリム。`/plans/create_and_execute` は `_get_param` で空文字→`None` 変換済み。
- ラベルは既存 CLI と同じ命名（英数字、`-`, `_`, `.` を想定）。`core/config/storage.get_planning_input_set` 側で `ValueError` を投げた場合は 400 を返し、レスポンスに `detail: "invalid input_set_label"` を含める。
- `config_version_id` が欠けている状態で `input_set_label` が指定された場合は 400。InputSet は Canonical version に紐付くため、version 不明な実行は禁止する。

### 2. API / ジョブでの伝播

| レイヤ | リクエスト入力 | フォールバック | レスポンス / 永続化 | 備考 |
|--------|----------------|----------------|----------------------|------|
| `/plans/create_and_execute` | `body.input_set_label` | なし | `plan_versions.input_set_label` と `runs.input_set_label` に保存 | `prepare_canonical_inputs(..., input_set_label=label)` として Canonical ビルダーへ引き渡す |
| `/plans/{version}/apply_adjusted` / `/reconcile` | `body.input_set_label` | `plan_versions.input_set_label` から復元 | 再計算成否のみ返却するが、内部で `prepare_canonical_inputs` を都度再実行 | 再実行時にラベル変更を許可（DBカラムを上書き保存） |
| `/runs`（同期） | `options.input_set_label` | なし | `runs.input_set_label` に反映 | `async=false` では Plan API 経由のレスポンスにそのまま含まれる |
| `/runs`（非同期） / `JobManager.submit_planning` | `options.input_set_label` | なし | `jobs.params_json`・`runs.input_set_label` | UIのジョブ詳細で InputSet を表示できるよう、`runs` テーブルに直接保存 |

### 3. ラベル永続化と再利用箇所
- **Plan artifact**: `_PLAN_INPUT_SET_ARTIFACT = "planning_input_set.json"` を導入済み。`db.upsert_plan_artifact` 経由で `{ "label": "<str>" }` を保存し、Plan detail / 再計算時のフォールバック値とする（DBカラム化後も当面は併用）。
- **DB Columns**: `plan_versions.input_set_label` と `runs.input_set_label` にラベルを直接永続化。APIレスポンスやUI表示ではこのカラムを正とする。
- **CanonicalConfig.meta.attributes**: `prepare_canonical_inputs` で `planning_input_label` を一時セット。`core/config/builders.build_planning_inputs` が `label`→`get_planning_input_set(label=...)` を優先呼び出し、未指定時は `config_version_id + status="ready"` で検索する。
- **ストレージフォールバック**: ラベル見つからず `PlanningInputSetNotFoundError` が投げられた場合、`_build_planning_bundle_from_canonical` にフォールバック。ログ `planning_input_set_demand_mismatch_detected` を WARN で出し、UI には「Fallback to canonical」の警告バナーを表示（Phase2で実装）。

### 4. UI / 可視化要件
- **Plan Create Form**: `/ui/plans` のフォームは `config_version_id` 選択時に `/ui/plans/input_sets?config_version_id=...` を呼び出し、`status="ready"` の InputSet をプルダウン表示する（未選択時は Legacy CSV 警告を表示）。
- **Plan Detail Overview**: InputSet カードで `label / status / source / updated_at` を表示し、`config_version_id` への導線と CLI エクスポート手順を提示。ラベルが無い場合は「Legacy CSV mode」と表示して注意喚起。
- **Run Detail Overview**: `runs.input_set_label` を使い、Plan detail と同等のカードを表示。ラベル未設定時は警告を出し、Plan連携がある場合は差分/Diff CTAへ誘導する。
- **Plan List / Run List**: テーブルに `InputSet` 列を追加済み。`/ui/plans?input_set_label=` と `/ui/runs?input_set_label=` でサーバーサイド絞り込みし、UI側も検索入力を同期する。
- **Diff/Resultsタブ**: InputSet 情報がある場合 `planning_inputs.json` の行数メタを示し、「入力セット差分をダウンロード」ボタンを表示。差分リンクは Export CLI (`scripts/export_planning_inputs.py --diff-against`) を叩く UI ボタンで代替する。

### 5. ログ・モニタリング
- `plan_store_input_set_label_failed` / `planning_job_store_input_set_label_failed` で `logging.exception` を発火済み。Prometheus カウンタ `plan_artifact_write_error_total{artifact="planning_input_set.json"}` を追加し、Plan artifact 書き込み失敗を可視化する（バックログ）。
- RunRegistry へラベル書き込みが行われなかった場合は `logging.warning("run_registry_missing_input_label", {"run_id": run_id, "plan_version": version_id})` を出す。
- `input_set_label` が指定されずに実行された場合、`legacy_mode_detected` という警告ログと `scpln_legacy_mode_runs_total` というPrometheusカウンターで記録する。

### 6. テスト観点
- `tests/test_canonical_builders.py` に `planning_input_label` 指定時の InputSet 読み込みテストを追加済み。今後は Plan API → artifact → RunRegistry までの e2e を `tests/test_plan_repository_views.py` に追加して回帰を防ぐ。
- APIレスポンス（`/plans/create_and_execute`）が `input_set_label` を返すこと、および指定無しで実行した場合に `None` を返すことを `tests/test_plan_repository_builders.py` にスモークとして追加する。

### 7. 残課題・次アクション
1. `gh` CLI や自動ジョブ用に InputSet 未指定実行の検知アラート（Slack通知）を追加し、運用上の逸脱を可視化する。
2. `app/run_compare_api` のリファクタリング。`input_set_label` フィルタを、RunRegistry summary への依存から、`runs` テーブルの `input_set_label` カラムを直接参照するように変更する。

## ハンドオフメモ（2025-11-09）
- **最新作業**: Legacyモード監視ロジックを `app/plans_api.py` と `app/runs_api.py` に実装。`input_set_label` がない実行を検知し、警告ログとPrometheusカウンターで記録する対応（T3-1）を完了しました。
- **ブランチ・コミット**: ここまでの作業はローカルブランチ `feat/legacy-mode-monitoring-ja` にコミット済みです。次回セッション開始時に `git push` およびPR作成と自動マージを実行してください。
- **次セッションの優先タスク**: 「7. 残課題・次アクション」に記載のタスクに着手してください。
- **注意点**: `app/plans_api.py` と `app/runs_api.py` が変更されています。特に `post_plans_create_and_execute` と `post_runs` で `input_set_label` の有無をチェックするロジックが追加されています。
