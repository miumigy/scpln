# 設定統合開発計画

- 最終更新: 2025-09-21
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

- [ ] T1.1: `core/config/models.py` にCanonicalモデル定義を追加しAlembicマイグレーションを実装
- [ ] T1.2: 設定整合チェック用の自動検証（重複ノード、リンク不整合、BOM循環など）を実装
- [ ] T1.3: 既存JSON/CSVからCanonicalへロードするシードスクリプトを作成

### PH2 ビルダー実装

- [ ] T2.1: Canonical→`SimulationInput` 変換ビルダーを実装し単体テストを追加
- [ ] T2.2: Canonical→Planning入力データ（Aggregate/Mix/Inventory等）を生成するビルダーを実装
- [ ] T2.3: ビルダー出力の検証テスト（PSI/Planning双方）を追加

### PH3 アプリ統合

- [ ] T3.1: `app/simulation_api.py` をビルダー経由で設定IDを受け取る実装に切替え後方互換パラメータを整理
- [ ] T3.2: `app/jobs.py` 計画ジョブでCSV読込を廃止しビルダー出力経由に変更
- [ ] T3.3: `plan_artifacts` へ設定スナップショットを保存し、Plan & Run のRun連携を更新

### PH4 UI/運用

- [ ] T4.1: `/ui/configs` にCanonical設定の閲覧・差分表示を追加
- [ ] T4.2: 設定編集フォームとCSV/JSONインポート機能を実装
- [ ] T4.3: ドキュメント（README, TUTORIAL）をCanonical運用に更新

### PH5 ロールアウト

- [ ] T5.1: 既存シナリオをCanonicalへ移行しリグレッションテストを実施
- [ ] T5.2: 移行後に不要となる旧CSVサンプル/エンドポイントの整理計画を決定
- [ ] T5.3: 運用手順書・トレーニング資料を更新

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

## 10. 更新履歴

- 2025-09-21: 初版作成。

