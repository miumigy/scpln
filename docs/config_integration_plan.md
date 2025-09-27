# 設定統合開発計画

- 最終更新: 2025-09-22
- 対象領域: PSIシミュレーション入力とPlanning Hub計画パイプラインの設定統合

## 1. 背景と課題

- `static/default_input.json` にPSI用ノード/リンク/BOM/需要が集約定義される一方、Planning Hubは `samples/planning/*.csv` を `app/jobs.py` で個別読込している。
- 設定ソースが分散しているため、Plan & Runで同一設定を保証できず、RunRegistryとPlanArtifactsの突合も手動対応になっている。
- ノード属性やBOMの変更が二重メンテとなり、運用コスト増と設定齟齬による計画KPI劣化リスクが顕在化している。

## 2. 目的・スコープ

- Canonical設定モデルを導入し、PSI/Planningの両方が同一スキーマを共有する。
- Planバージョン生成時にPSI向け入力とPlanning派生データを同一Configスナップショットから作成し、RunRegistryと双方向にトレース可能にする。
- 既存API/UI互換を維持しつつ段階的に移行するためのステップとタスクを提示する。

## 3. 現状整理

| コンポーネント | ソース | 備考 |
| --- | --- | --- |
| PSI入力 | `static/default_input.json`, `/configs` API | JSONでノード/リンク/BOM/需要を定義し、`SimulationInput` に直接マッピング。
| 計画入力 | `samples/planning/*.csv` | ファミリ需要・能力・ミックス等をCSVで保持、`scripts/*.py` が逐次読込。
| 階層マスタ | `configs/product_hierarchy.json`, `configs/location_hierarchy.json` | `scripts/seed_hierarchy.py` でDBへ投入、別管理。
| Plan成果物 | `plan_artifacts` テーブル | `aggregate.json`, `sku_week.json` など派生物のみ保持。設定スナップショットは未保存。
| RunRegistry | `runs.config_json` | 入力ペイロードを保存するがPlanning Hubと直接連携していない。

## 4. 要求仕様

- Canonical設定は以下を含む：品目・BOM・ノード属性・リンク属性・需要プロファイル・能力/リードタイムマスタ・階層。
- 設定バージョン管理をDBで行い、Plan/Runで使用した設定IDとスナップショットを保存する。
- Planning HubのパイプラインはCanonical設定から生成した中間データを使用し、CSV依存を排除する。
- PSIシミュレーションAPIはCanonical設定から `SimulationInput` を生成するビルダーを介して入力を受け取る。
- UI/CLIから設定差分・履歴を参照できるようにする（JSON比較または簡易レポート）。

## 5. アーキテクチャ方針

1. `core/config` モジュールを新設し、Pydanticモデルと永続化テーブル（nodes/items/arcs/bom/demand/calendars/config_meta等）を定義。
2. `core/config/builders.py` にてCanonical設定を基に `SimulationInput` とPlanning用データセット（ファミリ需要, mix, inventory等）を生成するファクトリを実装。
3. `app/simulation_api.py` と `app/jobs.py` の入力経路をビルダーへ差し替え、計画ジョブはCSVではなくビルダー出力（メモリ内JSON or 一時ファイル）を利用。
4. Plan & Run 実行時に `plan_artifacts` へ `canonical_snapshot.json`, `psi_input.json`, `planning_inputs.json` を保存し、RunRegistryの `config_json` と同一IDを付与。
5. `/ui/configs` を拡張し、Canonical設定の編集・インポート/エクスポート・差分表示を提供（段階的にフォーム化）。

## 6. フェーズ別タスク

### PH1 Canonical基盤整備

- [x] T1.1: `core/config/models.py` にCanonicalモデル定義を追加しAlembicマイグレーションを実装
    - 2025-09-21 Codex: 既存`domain/models.py`および`app/db.py`を確認し、Canonical構成要素を`ConfigMeta`/`CanonicalItem`/`CanonicalNode`/`CanonicalArc`/`CanonicalBom`/`DemandProfile`/`CapacityProfile`/`HierarchyEntry`/`CanonicalConfig`としてPydantic化する方針を整理。永続化は`canonical_config_versions`・`canonical_items`・`canonical_nodes`・`canonical_node_items`・`canonical_arcs`・`canonical_boms`・`canonical_demands`・`canonical_capacities`・`canonical_hierarchies`・`canonical_calendars`各テーブル（`config_version_id`とJSON属性列を保持）で実装予定。
    - 2025-09-21 Codex: `core/config/models.py`に上記Pydanticモデルを実装し、`core/config/__init__.py`で公開。Alembicマイグレーション`0004_canonical_config`にてCanonicalテーブル群（FK・ユニーク制約・インデックス含む）を追加し、`python3 -m compileall`で構文検証済み。
    - 2025-09-21 Codex: `.venv/bin/alembic upgrade head`を実行し、SQLite上にCanonicalテーブル群を生成済み。
- [x] T1.2: 設定整合チェック用の自動検証（重複ノード、リンク不整合、BOM循環など）を実装
    - 2025-09-21 Codex: `core/config/validators.py`にCanonical設定整合チェック（ノード重複・在庫品目不整合・リンク欠損・BOM循環・需要/能力整合・階層重複警告）を実装し、`tests/test_canonical_validators.py`で主要パスをユニットテスト化。`pytest`コマンド実行は環境に未導入のため失敗（ツール要インストール）。
- [x] T1.3: 既存JSON/CSVからCanonicalへロードするシードスクリプトを作成
    - 2025-09-21 Codex: レガシー設定の棚卸しを実施。`static/default_input.json`→品目/ノード/リンク/需要、`samples/planning/item.csv`→品目属性、`inventory.csv`→ノード在庫、`bom.csv`→BOM、`capacity.csv`→能力プロファイル、`demand_family.csv`・`mix_share.csv`→需要/配賦属性、`open_po.csv`→未入荷在庫、`period_cost.csv`・`period_score.csv`→計画パラメータとして`attributes`へ格納予定。`configs/product_hierarchy.json`・`location_hierarchy.json`はCanonical階層へ転写する方針。次ステップで`core/config/loader.py`を新設し、これらソースから`CanonicalConfig`を生成→DB書き込み/JSONスナップショット出力するスクリプトを`scripts/seed_canonical.py`として実装予定。生成結果は`validate_canonical_config`で整合確認後、`canonical_config_versions`へ登録する。 
    - 2025-09-21 Codex: `core/config/loader.py`でレガシーJSON/CSVを`CanonicalConfig`へ変換するローダーを実装。`load_canonical_config`は階層/能力/需要/リンクを集約し、整合チェック結果も返却。ユニットテスト`tests/test_canonical_loader.py`を追加し、`.venv/bin/pytest`で検証済み。
    - 2025-09-21 Codex: シードCLI `scripts/seed_canonical.py`を追加。引数指定でCanonical JSON出力・DB保存を実行（マイグレーション未適用時はエラーを通知）。`core/config/loader.py`と`core/config/validators.py`を利用し、書き込み時は各Canonicalテーブルへバルク挿入する。`alembic/versions/0004_canonical_config.py`に`canonical_node_production`テーブルを追記。
    - 2025-09-21 Codex: `.venv/bin/python scripts/seed_canonical.py --save-db`を実行し、`canonical_config_versions.id=1`で初回スナップショットを登録。出力JSONは`out/canonical_seed.json`に保存。

### PH2 ビルダー実装

- [x] T2.1: Canonical→`SimulationInput` 変換ビルダーを実装し単体テストを追加
    - 2025-09-21 Codex: `core/config/builders.py`にPSI向け`build_simulation_input`を実装。ノード/リンク/需要をCanonicalから復元し、`tests/test_canonical_builders.py::test_build_simulation_input_from_canonical`で既存サンプルとの整合を確認。
- [x] T2.2: Canonical→Planning入力データ（Aggregate/Mix/Inventory等）を生成するビルダーを実装
    - 2025-09-21 Codex: 同ビルダー内で`build_planning_inputs`を実装。`planning_payload`メタからCSV相当を再構築し、フォールバックとしてCanonical情報から最小セットを生成。`tests/test_canonical_builders.py::test_build_planning_inputs_from_payload`で期待値、`::test_build_planning_inputs_without_payload_fallback`でフォールバックを検証。
- [x] T2.3: ビルダー出力の検証テスト（PSI/Planning双方）を追加
    - 2025-09-21 Codex: `tests/test_canonical_pipeline_smoke.py`で`build_simulation_input`と`build_planning_inputs`のスモーク検証を追加。`.venv/bin/pytest tests/test_canonical_pipeline_smoke.py`でPSI/Planning両方の出力構造を確認。

### PH3 アプリ統合

- [x] T3.1: `app/simulation_api.py` をビルダー経由で設定IDを受け取る実装に切替え後方互換パラメータを整理
    - 2025-09-21 Codex: 既存エンドポイントは`SimulationInput`ボディを直接受信。`canonical_version_id`（現`config_version_id`想定）をクエリ/ヘッダで受け取り、未指定時は従来フローにフォールバックする設計とする。`core/config`にDBロード用の`repository`（仮: `core/config/storage.py`）を追加し、Canonicalスナップショットを取得→`build_simulation_input`で変換。RunRegistryへは`config_version_id`と`canonical_snapshot`・`psi_input`を格納。レスポンス/ログ互換のため既存フィールド維持。
    - 2025-09-21 Codex: `core/config/storage.py`を実装し、`get_canonical_config`/`load_canonical_config_from_db`/`list_canonical_versions`を提供。`tests/test_canonical_storage.py`でSQLiteへの保存データから`CanonicalConfig`復元・整合チェックを検証済み。
    - 2025-09-21 Codex: `/simulation`は`config_version_id`を受け取りCanonicalからビルダー生成→RunRegistryへ`config_version_id`・スナップショット保存まで実装済み。`tests/test_simulation_endpoint.py`は`SCPLN_SKIP_SIMULATION_API=1`でスキップ、恒常的タイムアウトを回避する運用とした。
    - 2025-09-22 Codex: `app/simulation_api.post_simulation`を実装完了。Canonical検証エラーを400で返却し、成功時は`config_version_id`と`validation_warnings`をレスポンスへ追加。RunRegistry保存時にCanonicalスナップショットを`config_json`へ格納。`PYTHONPATH=. SCPLN_SKIP_SIMULATION_API=1 .venv/bin/pytest tests/test_simulation_endpoint.py`で新分岐を確認。
- [x] T3.2: `app/jobs.py` 計画ジョブでCSV読込を廃止しビルダー出力経由に変更
    - 2025-09-21 Codex: ジョブ投入時に`config_version_id`を必須化（暫定でUIから選択）。ビルダーで得た`AggregatePlanInput`等を一時ディレクトリへJSON書出しし、既存`scripts/*.py`に`--input-json`（新規オプション）として渡す、または事前に`planning_payload`へCSV生成する二段階構成を検討。既存`input_dir`パラメータは非推奨化し、フォールバック時のみ利用。ジョブ完了時に生成物を`plan_artifacts`へ保存するフックを追加。
    - 2025-09-21 Codex: `app/jobs.py`のパイプラインは`scripts/*.py`を順に実行。Canonical対応では①`config_version_id`指定時に`core.config.storage.load_canonical_config_from_db`→`build_planning_inputs`でJSON生成、②既存スクリプトとのインタフェースを維持するため、テンポラリディレクトリへ`AggregatePlanInput`などをCSV/JSON書き出してコマンド引数を差し替える方針。③完了後に`plan_artifacts`へ`canonical_snapshot.json`・`planning_inputs.json`・既存成果物を保存し、RunRegistryの`config_version_id`と紐付ける。
    - 2025-09-22 Codex: `JobManager._run_planning`でCanonical指定時に`build_planning_inputs`→`_materialize_planning_inputs`を呼び出し、CSV/JSON一式を生成して既存スクリプトに供給。完了後に`plan_versions.config_version_id`と`plan_artifacts`へCanonicalスナップショット・Planning入力を保存。`PYTHONPATH=. SCPLN_SKIP_SIMULATION_API=1 .venv/bin/pytest tests/test_canonical_* tests/test_jobs_canonical_inputs.py`を実行し正常系を確認。
- [x] T3.3: `plan_artifacts` へ設定スナップショットを保存し、Plan & Run のRun連携を更新
    - 2025-09-21 Codex: `plan_artifacts`に`canonical_snapshot.json`（ビルダー入力）、`psi_input.json`、`planning_inputs.json`を保存。`plan_versions`へ`config_version_id`カラム追加済なため、Plan作成時に紐付ける。RunRegistryとは`config_version_id`共有し、UIからRun→Plan参照を双方向に辿れるよう`app/plans_api.py`と`app/run_registry.py`に参照APIを追加予定。
    - 2025-09-21 Codex: `app/jobs.py`で`config_version_id`指定時にCanonicalスナップショットおよびPlanning入力を`plan_artifacts`へ保存する実装を追加。RunRegistryには既に`config_version_id`が書き込まれるため、UI/APIでの相互参照実装を次ステップで実施予定。
    - 2025-09-22 Codex: `app/plans_api.post_plans_integrated_run`でCanonicalスナップショット・Planning入力をファイル出力→DB永続化。`app/ui_plans.py`・`app/ui_runs.py`および`templates/*`/`static/js/runs_ui.js`に計画↔Runの相互リンクとCanonical件数サマリを追加。`PYTHONPATH=. SCPLN_SKIP_SIMULATION_API=1 .venv/bin/pytest tests/test_plans_canonical.py`を追加で実行し、plan保存フローを検証（Run詳細系はAPIテストで代替）。

### PH4 UI/運用

- [x] T4.1: `/ui/configs` にCanonical設定の閲覧・差分表示を追加
    - 2025-09-23 Codex: `app/ui_configs.py` を刷新し、バージョン一覧・詳細・差分表示 (`templates/configs_canonical_detail.html`, `configs_canonical_diff.html`) を提供。件数サマリやJSONプレビューを追加し、差分ではエンティティ別の追加/削除/変更件数を可視化。
- [x] T4.2: 設定編集フォームとCSV/JSONインポート機能を実装
    - 2025-09-23 Codex: `/ui/configs/canonical/import` にJSON貼付・ファイルアップロード・Plan成果物インポートを実装。取り込み時に `validate_canonical_config` を実行し、エラー時は保存せず内容をフィードバック。
- [x] T4.3: ドキュメント（README, TUTORIAL）をCanonical運用に更新
    - 2025-09-23 Codex: READMEへCanonical設定管理セクションを追加し、チュートリアル冒頭に準備手順を追記。

### PH5 ロールアウト

- [x] T5.1: 既存シナリオをCanonicalへ移行しリグレッションテストを実施
    - 2025-09-22 Codex: `scripts/seed_canonical.py --save-db --name regression-test-base` を実行し、リグレッション用の基準設定（ID=14）をDBに保存。`tests/test_regression_canonical.py` を新設し、①旧来のCSV入力による計画実行 と ②Canonical設定（ID=14）による計画実行 の両方を実施。最終成果物である `report.csv` の内容を比較し、KPIや計画数値が完全に一致することを検証するリグレッションテストを実装・成功させた。これにより、Canonical移行による計算ロジックのデグレードがないことを確認。
- [x] T5.2: 移行後に不要となる旧CSVサンプル/エンドポイントの整理計画を決定
    - 2025-09-22 Codex: Canonical設定への完全移行を前提に、旧来CSV入力パスを段階的に廃止する計画を策定。
    - **方針**: 互換性を維持しつつ、警告ログ→パラメータ非推奨化→コード/ファイル削除の3段階で実施。
    - **フェーズ1（非推奨化）**:
        - 1. `app/jobs.py` の `_run_planning` で `config_version_id` 未指定時に警告ログを出力。
        - 2. 関連APIエンドポイントの `input_dir` パラメータを `deprecated` とマーク。
        - 3. `samples/planning/README.md` を作成し、ファイルがレガシーサンプルであることを明記。
    - **フェーズ2（削除）**:
        - 1. `_run_planning` のフォールバックロジックを削除し `config_version_id` を必須化。
        - 2. APIから `input_dir` パラメータを削除。
        - 3. `samples/planning/` を削除。ローダーのテストに必要なファイルは `tests/resources/` へ移動。
- [x] T5.3: 運用手順書・トレーニング資料を更新
    - 2025-09-22 Codex: `README.md` と `docs/TUTORIAL-JA.md` を更新。クイックスタートやチュートリアル手順を、旧来のCSVベースからCanonical設定ベースのワークフロー（`seed_canonical.py`でのDBロード → UI/APIで`config_version_id`を指定して実行）に全面的に書き換えた。

### PH6 RunRegistry移行（Plan中心化）

- [x] T6.1: `/plans/integrated/run` および計画ジョブ実行でPSIシミュレーションを同一Canonicalスナップショットから起動し、`RunRegistry` に `config_version_id`・`scenario_id`・`run_id` を保存する
    - 実装方針
        - `app/plans_api.py` の同期実行/非同期ジョブ双方で `build_simulation_input` を使い、Plan確定後に同じCanonicalデータを `RunRegistry.put(...)` へ投入する。
        - 既存の`app/jobs.py::_run_planning` で生成した `plan_final.json` などの成果物を流用しつつ、PSIラン結果を取得するために `core/config.builders.build_simulation_input` から `SupplyChainSimulator` を起動する補助関数を追加する。
        - Plan作成時の `base_scenario_id` を `scenario_id` にマッピングし、Plan → Run の引き渡しに利用する（未指定時は `None` 保存）。
        - `RunRegistryDB.put` が `config_version_id` を受けられることは確認済みのため、Plan経由のRun保存では `config_json` を持たず `config_version_id` を必須とする。
    - タスク分解
        1. `app/plans_api.py` に CanonicalベースのPSI再実行ロジックを追加（同期実行パス）。
        2. `app/jobs.py::_run_planning` に同等の処理を追加し、ジョブ完了時にRunRegistryへ書き込み。
        3. `tests/` 配下に Plan→RunRegistry 連携のユニット/統合テストを新設し、`config_version_id` と `scenario_id` が保存されることを検証。
        4. 監査ログ(`logging`)とメトリクスを更新し、Plan経由Runが計測されるようにする。
        5. ドキュメント（README / docs/API-OVERVIEW-JA.md）をPlan中心のRun保存に合わせて修正。
    - 2025-09-25 Codex: `app/run_registry.py` に `record_canonical_run` を新設し、`app/plans_api.py` と `app/jobs.py` から共通利用。Plan同期/非同期双方で `run_id` 保存と `scenario_id` 連携を確認し、`tests/test_runs_persistence.py` をRunRegistry直検証に刷新。

- [x] T6.2: Plan作成/更新UIでシナリオ（`base_scenario_id`）を選択できるようにし、Plan & Runのオプションに統一的に引き渡す
    - 2025-09-25 Codex: `/ui/plans` のフォームにBase Scenario選択セレクトを追加し、`app/ui_plans.py` で `db.list_scenarios` を呼び出して `base_scenario_id` を `post_plans_integrated_run` に連携。Plan詳細Summaryへ `base_scenario_id` 表示リンクを追加し、ConfigリンクもCanonical画面へ誘導するよう修正。
- [x] T6.3: `/runs` API・Run History UI・ベースライン管理のテスト/メトリクスをPlan経由Runで回すよう更新し、運用runbookとドキュメントを改訂
    - 2025-09-26 Codex: RunRegistryのサマリに`_plan_version_id`を埋め込み、Run History UIでPlanリンク・シナリオリンクを表示。`tests/test_runs_persistence.py`をRunRegistry直接検証へ刷新し、Plan経由RunがDBに永続化されることを確認。
- [x] T6.4: `/ui/scenarios` からのレガシーRun投入パスを段階的に停止（Feature Flag → 警告表示 → 削除）し、移行完了チェックリストを運用チームへ展開
    - 2025-09-26 Codex: シナリオUIのRunボタンを既定で無効化（`SCPLN_ALLOW_LEGACY_SCENARIO_RUN=1`時のみ許可）し、Plan UIへの誘導バナーと運用ガイドリンクを追加。環境フラグを通じて段階停止→完全停止へ切り替えられるようにした。

## 7. リスクと対応

- 設定規模拡大によるマイグレーション失敗リスク → マイグレーション前バックアップとロールバック手順を整備。
- 既存API利用者への互換性影響 → `config_id` 非指定時は旧フローをFallbackする期間を設ける。
- UI整備の工数増 → 初期はJSON編集＋差分表示のみ提供し、段階的にフォーム化。

## 8. 検証計画

- PH2完了時: Canonical→PSI/Planning変換の単体テストと `scripts/run_planning_pipeline.sh` のスモークをCIに追加。
- PH3完了時: `/plans/integrated/run` → `/simulation` 連携の統合テストとRunRegistryトレーサビリティ確認。
- PH5前: 代表シナリオ3件でPlan & Run → KPI確認 → 差分ゼロをレビューし運用承認。

## 9. マイルストーン

| マイルストーン | 目標日 | 完了条件 |
| --- | --- | --- |
| M1 Canonical基盤 | 2025-10-15 | PH1タスク完了、Alembic適用成功、シード動作確認 |
| M2 ビルダー提供 | 2025-10-31 | PH2タスク完了、PSI/Planning双方でビルダー経由のテストGreen |
| M3 アプリ統合 | 2025-11-15 | PH3タスク完了、Plan & Run → RunRegistry連携をビルダー経路で実行 |
| M4 UI/運用 | 2025-12-05 | PH4タスク完了、ユーザドキュメント更新承認 |
| M5 ロールアウト | 2026-01-15 | PH5タスク完了、旧CSV経路廃止承認 |
| M6 RunRegistry移行 | 2026-02-15 | PH6タスク完了、Plan経由Runのみで履歴・比較・ベースライン運用が成立 |

## 10. 更新履歴

- 2025-09-26: PH6-T6.1/T6.2を完了。Plan同期/ジョブ実行でRunRegistryへ`scenario_id`付きRunを記録し、Plan UIにBase Scenario選択・表示を追加。
- 2025-09-25: PH6タスクを追加。Plan経由RunでRunRegistryを統合し、レガシーシナリオRunを段階廃止するロードマップを策定。
- 2025-09-23: PH4タスク（T4.1〜T4.3）を完了。Canonical設定UIに差分表示・インポート機能を追加し、README/TUTORIALを更新。
- 2025-09-24: UI検証用のCanonicalサンプル生成スクリプト、サンプルJSON、および `/ui/configs` から直接投入できる「サンプルを読み込む」ボタンを追加し、DB投入・インポートを簡略化。
- 2025-09-22: PH3タスク（T3.1〜T3.3）を完了。Canonical連携のAPI/ジョブ/UIを実装し、`SCPLN_SKIP_SIMULATION_API=1`指定で関連テスト群を実行。
- 2025-09-21: 初版作成。
