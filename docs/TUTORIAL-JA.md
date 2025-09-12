# ハンズオン: Planning Hub チュートリアル（P-24）

本ガイドでは、Planning Hub（/ui/plans）を使って「作成→プレビュー→実行→結果確認」までを体験します。

## 前提
- サーバ起動済み（例）: `uvicorn main:app --reload`
- ブラウザで `http://localhost:8000` にアクセス可能

## 1. 新規Planを作成（統合Run）
1) `/ui/plans` を開く
2) 「新規Plan作成（統合Run）」フォームで以下を入力
   - `input_dir`: `samples/planning`
   - `weeks`: `4`
   - （任意）`cutover_date`、`anchor_policy` など
3) 「Run（作成）」ボタン
4) 作成されたプラン詳細（/ui/plans/{version_id}）に遷移

ヒント: 実行ログやKPIが画面下部に見えてきます。まずはOverviewで要約を掴みましょう。

## 2. プレビュー（Aggregate / Disaggregate / Validate）
- Aggregate: family×period で集計結果を確認
- Disaggregate: SKU×week の明細を簡易フィルタで確認（先頭200件）
- Validate: 自動チェック（Tol違反、負在庫、小数受入、能力超過）を確認

ヒント: 予定オーダ（Scheduleタブ）からCSV（schedule.csv）をDLできます。

## 3. 再整合（必要に応じて）
- Executeタブ → 「再整合（パラメータ指定）」
  - `cutover_date`、`recon_window_days`、`anchor_policy` などを調整
  - 「再整合を実行」
- Diffタブやエクスポート（compare.csv / violations_only.csv）で差分を確認

## 4. Plan & Run（自動補完）
- Executeタブ → 「Plan & Run（自動補完）」
  - 既存のcutover/window/policy を引き継ぎつつ、/runs API → /plans/integrated/run を起動
  - 同期/ジョブ投入（非同期）が選択可能

## 5. 結果確認（Results）
- 最新Runのリストや、比較（metrics/diffs）の一括コピーで共有
- タブを切り替え、KPIや差分、可視化（Chart.js）を参照

## 6. レガシーUIとの関係（P-14）
- 旧UI `/ui/planning` は廃止。Planning Hub（`/ui/plans`）を利用してください。
  - Phase 2: `/ui/plans` へ302（`?allow_legacy=1` で一時回避）
  - Phase 3: `HUB_LEGACY_CLOSE=1` で 404 ガイド（legacy_closed.html）を表示

## 7. APIで同等操作（参考）
- 統合Run（同期）
```bash
curl -sS http://localhost:8000/plans/integrated/run \
  -H 'content-type: application/json' \
  -d '{
        "input_dir":"samples/planning",
        "weeks":4,
        "round_mode":"int",
        "lt_unit":"day",
        "cutover_date":"2025-01-15",
        "anchor_policy":"blend"
      }' | jq .
```
- 予定オーダCSV
```bash
curl -sS http://localhost:8000/plans/<version_id>/schedule.csv -o schedule.csv
```
- Run API（Plan & Run相当）
```bash
curl -sS http://localhost:8000/runs -H 'content-type: application/json' -d '{
  "pipeline":"integrated",
  "async":false,
  "options":{"input_dir":"samples/planning","weeks":4,"lt_unit":"day"}
}' | jq .
```

## 8. 用語と参照
- 用語表: `docs/TERMS-JA.md`
- API概要: `docs/API-OVERVIEW-JA.md`
