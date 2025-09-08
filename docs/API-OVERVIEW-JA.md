# API概要（Planning Hub関連, P-23）

本リポジトリで提供する主要エンドポイントの概要です。用語は `docs/TERMS-JA.md` に準拠します。

## ヘルス/メトリクス
- GET `/healthz` ヘルスチェック
- GET `/metrics` Prometheusメトリクス（plans_created_total ほか）

## Planning Hub UI（HTML）
- GET `/ui/plans` プラン一覧（作成フォーム含む）
- POST `/ui/plans/run` 統合Runで新規Plan作成（同期）
- GET `/ui/plans/{version_id}` プラン詳細（タブ: Overview/Aggregate/Disaggregate/Schedule/Validate/Execute/Results）
- POST `/ui/plans/{version_id}/plan_run_auto` Plan & Run（自動補完; /runs経由で新規Plan）
- POST `/ui/plans/{version_id}/reconcile` 再整合実行（必要に応じanchor/adjusted）
- POST `/ui/plans/{version_id}/state/advance` / `/state/invalidate` state遷移/無効化

## Planning API（JSON/CSV）
- GET `/plans` 登録済みPlan一覧
- POST `/plans/integrated/run` 統合パイプライン実行（aggregate→allocate→mrp→reconcile）し、新規Plan登録
- GET `/plans/{version_id}/summary` Plan要約（reconciliation summary / weekly_summary）
- GET `/plans/{version_id}/compare` 差分一覧（violations_only, sort, limit）
- GET `/plans/{version_id}/compare.csv` 上記のCSV出力
- GET `/plans/{version_id}/carryover.csv` anchor/carryoverの遷移CSV出力
- GET `/plans/{version_id}/schedule.csv` 予定オーダ（mrp.jsonから）CSV出力
- POST `/plans/{version_id}/reconcile` aggregate×DETの整合評価（before/adjusted）

## Run API（統合アダプタ, P-16）
- POST `/runs` body例:
  ```json
  {
    "pipeline": "integrated",
    "async": false,
    "options": {
      "input_dir": "samples/planning",
      "weeks": 4,
      "lt_unit": "day",
      "cutover_date": "2025-01-15",
      "recon_window_days": 7,
      "anchor_policy": "blend",
      "tol_abs": 1e-6,
      "tol_rel": 1e-6,
      "calendar_mode": "simple",
      "carryover": "auto",
      "carryover_split": 0.5,
      "apply_adjusted": false
    }
  }
  ```
  - 同期時: `{status:"succeeded", version_id, location:"/ui/plans/{version_id}"}`
  - 非同期時: `{status:"queued", job_id, location:"/ui/jobs/{job_id}"}`

## 比較（CSV）
- GET `/ui/compare/metrics.csv?run_ids={id1},{id2}` 指標比較CSV
- GET `/ui/compare/diffs.csv?run_ids={id1},{id2}&threshold=5` 差分比較CSV

## レガシーUI
- GET `/ui/planning` 段階的クローズ（Phase2: /ui/plansへ302, Phase3: 404ガイド）。`?allow_legacy=1` で一時回避可能。

備考:
- すべてのJSON/CSVはUTF-8。CSVはtext/csv; charset=utf-8で返却。
- 認証は環境変数 `AUTH_MODE`（none/apikey/basic）で切替。
