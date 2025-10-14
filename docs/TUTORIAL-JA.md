# ハンズオン: Planning Hub チュートリアル

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
2) 「新規Plan作成（統合実行）」ボタンをクリックしてフォームを開きます。
3) 以下の項目を入力します。
   - **Canonical設定バージョン**: 先ほどロードした設定のIDを選択します（通常は一覧の最上位）。
   - **計画週数 (weeks)**: `8`
   - （任意）`カットオーバー日`、`アンカー方針` などを指定します。
4) 「作成と実行」ボタンをクリックします。
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

## 4. Plan & Execute（自動補完）
- Executeタブ → 「再整合（パラメータ指定）」
  - `cutover_date`、`recon_window_days`、`anchor_policy` などを調整
  - 「再整合を実行」
- Diffタブやエクスポート（compare.csv / violations_only.csv）で差分を確認

## 5. Runの確認とPSIシミュレーション

### 5.1 PlanとRunの概念

Planning Hubにおける「Plan」と「Run」は、サプライチェーン計画シミュレーションの異なる側面を表します。

-   **Plan (計画)**: シミュレーションの「入力」となる、一連の設定とデータ（需要予測、在庫ポリシー、生産能力、BOMなど）をまとめたものです。Planはバージョン管理されており、特定の`config_version_id`に関連付けられます。`/ui/plans`で作成・管理されます。
-   **Run (実行)**: 特定のPlanに基づいてシミュレーションを実行した「結果」です。Runには、シミュレーションのサマリー、主要業績評価指標（KPI）、日次損益、コストトレースなどの詳細なデータが含まれます。一つのPlanから、異なるパラメータやシナリオで複数のRunを生成し、結果を比較検討することが可能です。

簡単に言えば、Planは「何をシミュレーションするか」を定義し、Runは「シミュレーションした結果どうなったか」を示します。

### 5.2 `/ui/runs`での結果確認

`/ui/runs`は、実行されたすべてのシミュレーション結果（Run）を一覧で確認できるUIです。

1.  **`/ui/runs`にアクセス**: ブラウザで `http://localhost:8000/ui/runs` を開きます。
2.  **Runの一覧表示**: 過去に実行されたシミュレーションのRunがリスト表示されます。各Runには以下の情報が含まれます。
    -   `run_id`: 各Runを一意に識別するID。
    -   `started_at`: シミュレーションが開始された日時。
    -   `duration_ms`: シミュレーションの実行時間（ミリ秒）。
    -   `config_id`, `scenario_id`, `plan_version_id`: そのRunがどの設定、シナリオ、Planに基づいて実行されたかを示します。
    -   `summary`: フィルレート、総利益などの主要なサマリー情報。
3.  **Runの詳細確認**: 特定の`run_id`をクリックすると、`/ui/runs/{run_id}`でそのRunの詳細画面に遷移します。
    -   詳細画面では、Runのサマリー、KPI、日次損益グラフ、コストトレース、実行時の設定（config_json）などを確認できます。
    -   関連するPlanが存在する場合、そのPlanのKPIサマリーも表示されます。

### 5.3 PSIシミュレーションの概要

Planning Hubで実行されるシミュレーションは、主にPSI (Production, Sales, Inventory) シミュレーションの概念に基づいています。これは、生産、販売、在庫の3つの要素のバランスを最適化し、サプライチェーン全体のパフォーマンスを最大化するための計画を立てるものです。

`app/runs_api.py`を通じてシミュレーションを実行する際に指定できるオプション（例: `weeks`, `round_mode`, `lt_unit`, `config_version_id`など）は、このPSIシミュレーションの重要なパラメータとして機能します。

-   `weeks`: シミュレーションの対象期間を週単位で指定します。
-   `round_mode`: 計画数量の丸め方を指定します（例: 整数丸め）。
-   `lt_unit`: リードタイムの単位を指定します（例: 日、週）。
-   `config_version_id`: シミュレーションに使用する設定のバージョンを指定します。

これらのパラメータを調整することで、異なるPSI計画シナリオを評価し、ビジネス目標に最適なサプライチェーン戦略を導き出すことができます。

## 6. 結果確認（Results）
- 最新Runのリストや、比較（metrics/diffs）の一括コピーで共有
- タブを切り替え、KPIや差分、可視化（Chart.js）を参照

## 7. APIでの操作例（参考）

- **統合Run（同期）**

```bash
# config_version_id は事前にDBにロードしたものを指定
CONFIG_VERSION_ID=14

curl -sS http://localhost:8000/plans/create_and_execute \
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
