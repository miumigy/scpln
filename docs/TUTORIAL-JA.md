# ハンズオン: Planning Hub チュートリアル（P-24）

本ガイドの目的と範囲:

- Planning Hub（/ui/plans）の基本操作を手順に沿って体験する
- 計画パイプラインやアルゴリズムの詳細は `docs/AGG_DET_RECONCILIATION_JA.md` を参照
- UI設計やロードマップは README の「Planning Hub」セクションに集約済み

操作フローと用語を把握した上で、必要に応じて README の「ドキュメントマップ」から他資料へ遷移してください。

## 前提
- サーバ起動済み（例）: `uvicorn main:app --reload`
- ブラウザで `http://localhost:8000` にアクセス可能

## 0. 設定の準備

本チュートリアルでは、事前に定義されたサンプル設定をデータベースにロードして使用します。

1.  **サンプル設定のロード**

    ターミナルから以下のコマンドを実行し、標準のサンプル設定をDBにロードします。

    ```bash
    # プロジェクトルートで実行
    PYTHONPATH=. python3 scripts/seed_canonical.py --save-db
    ```

2.  **設定の確認**

    - ブラウザで `/ui/configs` を開きます。
    - 先ほどロードした設定（例: `canonical-seed`）が一覧に表示されていることを確認します。
    - この画面から、設定の詳細を閲覧したり、バージョン間の差分を比較したりできます。


## 1. 新規Planを作成

1) `/ui/plans` を開きます。
2) 「新規Plan作成（統合Run）」ボタンをクリックしてフォームを開きます。
3) 以下の項目を入力します。
   - **Canonical設定バージョン**: 先ほどロードした設定のIDを選択します（通常は一覧の最上位）。
   - **計画週数 (weeks)**: `8`
   - （任意）`カットオーバー日`、`アンカー方針` などを指定します。
4) 「Run（作成）」ボタンをクリックします。
5) 作成されたプラン詳細ページ（`/ui/plans/{version_id}`）に自動的に遷移します。このとき、生成されたPlanのデータは、従来のファイル形式ではなくデータベースに直接保存され、版管理されます。

ヒント: 実行が完了すると、画面下部に実行ログやKPIサマリが表示されます。まずは「Overview」タブで計画の全体像を把握しましょう。

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

## 7. APIでの操作例（参考）

- **統合Run（同期）**

```bash
# config_version_id は事前にDBにロードしたものを指定
CONFIG_VERSION_ID=14

curl -sS http://localhost:8000/plans/integrated/run \
  -H 'content-type: application/json' \
  -d "{
        \"config_version_id\":${CONFIG_VERSION_ID},
        \"weeks\":8,
        \"round_mode\":\"int\",
        \"lt_unit\":\"day\",
        \"cutover_date\":\"2025-09-01\",
        \"anchor_policy\":\"blend\",
        \"storage_mode\":\"db\"
      }" | jq .
```

- **予定オーダCSVのダウンロード**

```bash
# {version_id} は上記コマンドのレスポンスに含まれるものを指定
curl -sS http://localhost:8000/plans/{version_id}/schedule.csv -o schedule.csv
```

- **Run API経由での実行**

```bash
# config_version_id は事前にDBにロードしたものを指定
CONFIG_VERSION_ID=14

curl -sS http://localhost:8000/runs -H 'content-type: application/json' -d "{
  \"pipeline\":\"integrated\",
  \"async\":false,
  \"options\":{
    \"config_version_id\":${CONFIG_VERSION_ID},
    \"weeks\":8,
    \"lt_unit\":\"day\"
  }
}" | jq .
```

## 8. 用語と参照
- 用語表: `docs/TERMS-JA.md`
- API概要: `docs/API-OVERVIEW-JA.md`
