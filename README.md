# サプライチェーン計画シミュレーション

[![CI](https://github.com/miumigy/scpln/actions/workflows/ci.yml/badge.svg)](https://github.com/miumigy/scpln/actions/workflows/ci.yml)

このプロジェクトは、部品表 (BOM) をサポートし、在庫補充ポリシーに基づいたサプライチェーンシミュレーションを提供します。需要の伝播、工場での生産と材料消費、リードタイムを考慮した在庫管理をシミュレートし、日ごとの詳細な結果を可視化します。

## 機能

*   **柔軟なシミュレーション入力**: 製品の部品構成表 (BOM)、ノード（店舗、倉庫、工場、サプライヤー）、ネットワーク接続、顧客需要をJSON形式で柔軟に定義できます。
*   **在庫補充ポリシー**: 各ノードは、サービスレベルに応じて設定された発注点 (`reorder_point`) と目標在庫レベル (`order_up_to_level`) に基づいて、自動的に上流ノードへ発注を行います。最小発注量 (`moq`) と発注倍数（`order_multiple`）は「ノード単位」に加えて「リンク（`network`）単位」でも設定でき、両方が指定された場合はより厳しい制約（MOQは大きい方、発注倍数は両者を同時に満たす倍数＝LCM）を適用します。
*   **需要の伝播と在庫管理**: 下流ノードで発生した需要（顧客需要や発注）は、サプライチェーンを遡って上流ノードの需要として適切に伝播されます。
*   **リードタイムの考慮**: 発注から入荷までのリードタイムがシミュレーションに反映され、輸送中の在庫が管理されます。
*   **詳細な日次シミュレーション結果の表形式表示**: シミュレーション結果は、日ごとの各ノード・各品目に関する詳細な指標が表形式で表示されます。
*   **収支機能**: 各ノードの保管費用、フローコスト（材料原価、生産、輸送）を固定費・変動費に分けて計算し、日別の収支表を表示します。
*   **キャパシティ制約**: フロー（輸送・生産）とストック（保管）にキャパシティを設定可能。超過を許容/不許可の選択と、許容時の追加固定・変動費の計上に対応。
*   **UI改善**: タブ切り替えUI、実行結果のノード・品目フィルタ機能、数値のカンマ区切り整数表示。

## セットアップと起動

1.  **Pythonの確認**: Python 3.9以上がインストールされていることを確認してください。
2.  **プロジェクトルートへ移動**:
    ```bash
    cd /home/miumigy/genai/scpln
    ```
3.  **起動スクリプトでサーバ起動（推奨）**:
    ```bash
    bash scripts/serve.sh                 # 通常起動
    RELOAD=1 bash scripts/serve.sh        # コード変更を自動再起動
    # 以降は http://localhost:8000 へアクセス
    ```
    - 初回実行時は `.venv` を自動作成し、`requirements.txt` を元に依存関係をインストールします。
4.  **サーバ停止**:
    ```bash
    bash scripts/stop.sh
    ```
5.  **手動でのセットアップ/起動（参考）**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --loop asyncio
    ```

## シミュレーションの実行 (Web UI)

1.  **ブラウザでアクセス**: `http://localhost:8000` を開きます。
2.  **シミュレーション実行**: JSONエディタのサンプル入力を使うか独自定義を貼り付け、「シミュレーション実行」をクリックします。
3.  **APIドキュメント**
    - OpenAPI UI: `http://localhost:8000/docs`
    - ReDoc: `http://localhost:8000/redoc`

## 運用コマンド

- 起動: `bash scripts/serve.sh`（`RELOAD=1` で自動再起動）
- 停止: `bash scripts/stop.sh`
- ステータス表示: `bash scripts/status.sh`（PID/ポート/ヘルス/直近ログ）
- ヘルスチェックのみ: `bash scripts/health.sh`

## ヘルスチェック

- エンドポイント: `GET /healthz`
- 確認例:
  ```bash
  curl -fsS http://localhost:8000/healthz && echo ok
  ```

## シミュレーション入力 (JSON構造)

シミュレーションの入力は、以下の構造を持つJSONオブジェクトです。`index.html` のJSONエディタに表示されているサンプル入力は、この構造の具体例です。

```json
{
    "planning_horizon": 100,
    "products": [
        {
            "name": "完成品A",
            "sales_price": 1500,
            "assembly_bom": [
                { "item_name": "材料X", "quantity_per": 2 },
                { "item_name": "材料Y", "quantity_per": 5 }
            ]
        }
    ],
    "nodes": [
        { "name": "店舗1", "node_type": "store", "initial_stock": { "完成品A": 30 }, "service_level": 0.95, "moq": {"完成品A": 10}, "order_multiple": {"完成品A": 5}, "storage_cost_fixed": 100, "storage_cost_variable": {"完成品A": 0.5}, "backorder_enabled": true },
        { "name": "中央倉庫", "node_type": "warehouse", "initial_stock": { "完成品A": 100 }, "service_level": 0.90, "storage_cost_fixed": 500, "storage_cost_variable": {"完成品A": 0.2}, "backorder_enabled": true },
        { "name": "組立工場", "node_type": "factory", "producible_products": ["完成品A"], "initial_stock": { "完成品A": 50, "材料X": 500, "材料Y": 800 }, "lead_time": 14, "production_capacity": 50, "reorder_point": {"材料X": 200, "材料Y": 400}, "order_up_to_level": {"材料X": 500, "材料Y": 800}, "moq": {"材料X": 50, "材料Y": 100}, "order_multiple": {"材料X": 25, "材料Y": 50}, "production_cost_fixed": 10000, "production_cost_variable": 50, "storage_cost_fixed": 1000, "storage_cost_variable": {"完成品A": 0.3, "材料X": 0.1, "材料Y": 0.1}, "backorder_enabled": true },
        { "name": "サプライヤーX", "node_type": "material", "initial_stock": { "材料X": 10000 }, "material_cost": {"材料X": 100}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料X": 0.01}, "backorder_enabled": true },
        { "name": "サプライヤーY", "node_type": "material", "initial_stock": { "材料Y": 10000 }, "material_cost": {"材料Y": 20}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料Y": 0.01}, "backorder_enabled": true }
    ],
    "network": [
        { "from_node": "中央倉庫", "to_node": "店舗1", "transportation_cost_fixed": 200, "transportation_cost_variable": 3, "lead_time": 3, "moq": {"完成品A": 20}, "order_multiple": {"完成品A": 10} },
        { "from_node": "組立工場", "to_node": "中央倉庫", "transportation_cost_fixed": 500, "transportation_cost_variable": 2, "lead_time": 7 },
        { "from_node": "サプライヤーX", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 30 },
        { "from_node": "サプライヤーY", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 20 }
    ],
    "customer_demand": [
        { "store_name": "店舗1", "product_name": "完成品A", "demand_mean": 15, "demand_std_dev": 2 }
    ]
}
```

### 複数店舗の追加（JSONのみで可能）

以下の3箇所にエントリを追加するだけで、店舗をいくつでも増やせます（コード変更不要）。

1) `nodes` に店舗ノードを追加

```
{ "name": "店舗2", "node_type": "store", "initial_stock": { "完成品A": 25 }, "service_level": 0.95, "moq": {"完成品A": 10}, "order_multiple": {"完成品A": 5}, "storage_capacity": 200, "allow_storage_over_capacity": true, "storage_cost_fixed": 100, "storage_cost_variable": {"完成品A": 0.5}, "backorder_enabled": true }
```

2) `network` に上流とのリンクを追加（例: 倉庫→店舗2）

```
{ "from_node": "中央倉庫", "to_node": "店舗2", "transportation_cost_fixed": 200, "transportation_cost_variable": 3, "lead_time": 3, "moq": {"完成品A": 20}, "order_multiple": {"完成品A": 10} }
```

3) `customer_demand` に当該店舗の需要を追加

```
{ "store_name": "店舗2", "product_name": "完成品A", "demand_mean": 10, "demand_std_dev": 2 }
```

UIのデフォルトサンプル（`static/js/main.js` 内の `sampleInput`）も店舗2を含む構成に更新済みです。

## 発注ロジック（在庫ポジションの定義）

発注判断はノード種別ごとに「在庫ポジション（Inventory Position, IP）」を用いて行います。IPには未着のパイプライン在庫も含め、過剰発注を防ぎます。

- 店舗（Store）/ 倉庫（Warehouse）
  - 需要モデル: サービスレベルに基づく標準偏差付きの需要（店舗は顧客需要、倉庫は配下店舗の合算需要プロファイル）
  - 発注点: `order_up_to = z * σ * sqrt(LT) + μ * (LT + 1)`
  - 在庫ポジション（当日の発注判定時）:
    - 店舗: `IP = 手持ち在庫 + 将来の入荷予定 - 顧客バックオーダー`
    - 倉庫: `IP = 手持ち在庫 + 将来の入荷予定 - 将来の出荷確定分（店舗向け）`
  - 将来の入荷予定: `pending_shipments`（および互換の `in_transit_orders`）から当日より後に着荷予定の数量を集計します。
  - 将来の出荷確定分: 倉庫が将来出荷予定として持つ `pending_shipments`（リンク: 倉庫→店舗）の合計を控除します。

- 工場（Factory）
  - 完成品（Store/Warehouse同様にサービスレベル制御）
    - `IP = 手持ち在庫 + 将来の完成予定（production_orders）`
  - 資材（Min-Max/補充点方式）
    - `IP = 手持ち在庫 + 将来の入荷予定（pending_shipments/in_transit）`
    - `IP <= reorder_point` のとき `order_up_to_level` まで補充（MOQ・発注倍数を適用）

- MOQ/発注倍数の適用
  - ノード側・リンク側の両方を考慮します。
  - MOQは大きい方を採用。
  - 発注倍数は両者が整数なら最小公倍数（LCM）へ丸め、それ以外は順次切り上げ。

これらの修正により、サプライヤ側の不足でバックオーダーが繰り越された場合でも、将来の入荷/出荷確定分を織り込んだ発注量となり、供給回復時の在庫膨張（雪だるま）を抑制します。

### バックオーダー設定（任意）

- 各ノードで `backorder_enabled` を設定可能です。
- 既定値: すべてのノードで `true`（必要に応じて `false` を指定してください）。
- 動作: 出荷日に在庫不足が発生した場合、`true` のノードは不足分を翌日以降に繰り越して再出荷を試みます。`false` のノードは不足分をその日の `shortage` として確定し、繰り越しません。

### リードタイムの設定

- 輸送リードタイムは `network[].lead_time` に設定してください（注文から到着までの日数）。
- 工場の生産リードタイムは工場ノードの `lead_time` を使用します。
- 店舗・倉庫・資材ノードの `lead_time` は輸送には使用しません。

## シミュレーション仕様（要点）

- 需要の定義: すべてのノード・品目で `demand = sales + shortage` が成立します。
- 需要の発生日: 上流ノードの需要は「注文日 + `network.lead_time`（リンクの輸送LT）」の出荷日に発生します。
- バックオーダー:
  - 各ノードは `backorder_enabled` が `true` の場合、出荷日に不足した数量を翌日以降に繰越して再出荷を試みます。
  - 店舗は顧客バックオーダーを保持し、入荷後に可能な範囲で自動出荷して消化します。
  - 実行結果表の「Backorder」は、未出荷の繰越分（上流の不足繰越＋店舗の顧客バックオーダー）の当日残高です。
  - 補充判断は在庫ポジション（上記「発注ロジック」参照）に基づき、未着のパイプラインや将来の出荷確定分を反映します。

## シミュレーション出力

シミュレーション結果は、日ごとの各ノード・各品目に関する以下の指標が表形式で表示されます。

*   **Day**: シミュレーションの日数
*   **Node**: ノード名
*   **Item**: 品目名
*   **Start Stock**: その日の開始時点の在庫
*   **Incoming**: その日に入荷した数量
*   **Demand**: その日に発生した需要（下流からの発注を含む）
*   **Sales**: その日に販売/供給された数量
*   **Consumption**: 工場で消費された材料の数量
*   **Produced**: 工場で生産された製品の数量
*   **Shortage**: その日に発生した欠品数量
*   **Backorder**: 未出荷の繰越残高（上流の不足繰越＋店舗の顧客バックオーダー）
*   **End Stock**: その日の終了時点の在庫
*   **Ordered**: その日に発注された数量

収支表は、以下の詳細なコスト分類で表示されます。

*   **Revenue**
*   **Material Cost**
*   **Flow Costs**
    *   Material Transport (Fixed/Variable)
    *   Production (Fixed/Variable)
    *   Warehouse Transport (Fixed/Variable)
    *   Store Transport (Fixed/Variable)
    
  計上ルール（概要）:
  - 輸送コストは「出荷日」に計上（固定費はリンクあたり1回/日、変動費は出荷数量比例）。
  - 材料原価は「資材→工場」の実出荷数量 × サプライヤーの `material_cost[item]`。
  - 生産費は当日の `produced` に応じて変動費、当日生産があれば固定費を計上。
*   **Stock Costs**
    *   Material Storage (Fixed/Variable)
    *   Factory Storage (Fixed/Variable)
    *   Warehouse Storage (Fixed/Variable)
    *   Store Storage (Fixed/Variable)
*   **Total Cost**
*   **Profit/Loss**

## バックアップ情報

シミュレーションの重要な変更は、プロジェクトルートの `backup/` ディレクトリにタイムスタンプ付きで保存されます。これにより、以前の状態にいつでも戻すことができます。

## 今後の拡張案

*   **需要予測の高度化**: 現在のランダムな需要パターンに加え、季節性やトレンドなどのより複雑な需要パターンを導入する。
*   **リードタイムの変動性**: リードタイムに不確実性（ランダムな変動）を導入し、より現実的なシミュレーションを行う。
*   **キャパシティ制約の追加**: 生産能力だけでなく、倉庫容量や輸送能力などの制約を導入する。
*   **異なる在庫ポリシーの比較**: Min-Max法以外の在庫ポリシー（例: 固定発注量方式、定期発注方式など）を実装し、比較分析を行う。
*   **特定のシナリオ分析**: 現在のモデルで、特定のシナリオ（例: サプライヤーのリードタイムが倍になった場合、需要が急増した場合など）をシミュレーションし、その影響を分析する。
### MOQ / 発注倍数の設定

- 対応ノード:
  - 工場（部品購買）: `moq`, `order_multiple`
  - 倉庫/店舗（上流への補充）: `moq`, `order_multiple`（任意）
- 丸め順序: `qty_to_order` を計算後、(1) `moq` 未満なら `moq` へ繰上げ、(2) `order_multiple` があれば倍数へ繰上げ（切上げ）。
- 単位: すべて品目の基準単位（EA）。ケース入数等は `order_multiple` で表現してください。
### キャパシティ設定

- 輸送リンク（`network[]`）:
  - `capacity_per_day`: 1日あたりの輸送キャパシティ（数量）。未指定時は無制限。
  - `allow_over_capacity`: 超過許容（true/false）。trueの場合、超過量に対するコストを設定可能。
  - `over_capacity_fixed_cost`, `over_capacity_variable_cost`: 超過発生日に1回の固定費、超過数量×単価の変動費。
- 生産（工場ノード）:
  - `production_capacity`: 1日あたりの生産キャパシティ（既存）。
  - `allow_production_over_capacity`: 超過許容（true/false）。
  - `production_over_capacity_fixed_cost`, `production_over_capacity_variable_cost`: 超過発生日に固定費/超過数量×単価を追加計上。
- 保管（全ノード）:
  - `storage_capacity`: ノード全体の保管キャパシティ（全品目合計数量）。
  - `allow_storage_over_capacity`: 超過許容（true/false）。falseの場合、入荷はキャパシティまでで残りは翌日へ持ち越し。
  - `storage_over_capacity_fixed_cost`, `storage_over_capacity_variable_cost`: 許容時の追加コスト（固定/超過数量×単価）。

## 再現シナリオ（バックオーダー誘発）

バックオーダーが発生する状況下での挙動確認用の最小構成です。READMEの「発注ロジック」に基づき、将来の入荷/出荷確定分を在庫ポジションに反映して過剰発注を抑制することを確認できます。

- 手順: Web UI の設定JSONに以下を貼り付けて実行します。
- 観察ポイントは下記の通りです。

```json
{
  "planning_horizon": 30,
  "products": [
    {"name": "完成品A", "sales_price": 1500, "assembly_bom": [
      {"item_name": "材料X", "quantity_per": 2},
      {"item_name": "材料Y", "quantity_per": 5}
    ]}
  ],
  "nodes": [
    {"name": "店舗1", "node_type": "store", "initial_stock": {"完成品A": 5}, "service_level": 0.95, "moq": {"完成品A": 10}, "order_multiple": {"完成品A": 5}, "storage_capacity": 200, "allow_storage_over_capacity": true, "storage_cost_fixed": 100, "storage_cost_variable": {"完成品A": 0.5}, "backorder_enabled": true},
    {"name": "中央倉庫", "node_type": "warehouse", "initial_stock": {"完成品A": 0}, "service_level": 0.90, "moq": {"完成品A": 30}, "order_multiple": {"完成品A": 10}, "storage_capacity": 500, "allow_storage_over_capacity": false, "storage_cost_fixed": 500, "storage_cost_variable": {"完成品A": 0.2}, "backorder_enabled": true},
    {"name": "組立工場", "node_type": "factory", "producible_products": ["完成品A"], "initial_stock": {"完成品A": 0, "材料X": 200, "材料Y": 400}, "lead_time": 14, "production_capacity": 50, "allow_production_over_capacity": true, "production_over_capacity_fixed_cost": 2000, "production_over_capacity_variable_cost": 10, "reorder_point": {"材料X": 100, "材料Y": 200}, "order_up_to_level": {"材料X": 300, "材料Y": 600}, "moq": {"材料X": 50, "材料Y": 100}, "order_multiple": {"材料X": 25, "材料Y": 50}, "storage_capacity": 1000, "allow_storage_over_capacity": true, "storage_cost_fixed": 1000, "storage_cost_variable": {"完成品A": 0.3, "材料X": 0.1, "材料Y": 0.1}, "backorder_enabled": true},
    {"name": "サプライヤーX", "node_type": "material", "initial_stock": {"材料X": 10000}, "material_cost": {"材料X": 100}, "backorder_enabled": true},
    {"name": "サプライヤーY", "node_type": "material", "initial_stock": {"材料Y": 10000}, "material_cost": {"材料Y": 20}, "backorder_enabled": true}
  ],
  "network": [
    {"from_node": "中央倉庫", "to_node": "店舗1", "transportation_cost_fixed": 200, "transportation_cost_variable": 3, "capacity_per_day": 50, "allow_over_capacity": false, "lead_time": 3, "moq": {"完成品A": 20}, "order_multiple": {"完成品A": 10}},
    {"from_node": "組立工場", "to_node": "中央倉庫", "transportation_cost_fixed": 500, "transportation_cost_variable": 2, "capacity_per_day": 100, "allow_over_capacity": false, "lead_time": 7},
    {"from_node": "サプライヤーX", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "capacity_per_day": 200, "allow_over_capacity": true, "lead_time": 30},
    {"from_node": "サプライヤーY", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "capacity_per_day": 200, "allow_over_capacity": true, "lead_time": 20}
  ],
  "customer_demand": [
    {"store_name": "店舗1", "product_name": "完成品A", "demand_mean": 20, "demand_std_dev": 3}
  ]
}
```

観察ポイント
- 初期数日で店舗は欠品し、顧客バックオーダーが増加します。
- 倉庫にも在庫が無く、倉庫→店舗の出荷はバックオーダーとして繰り越されます。
- 補充発注では、店舗は「将来の入荷予定 − 顧客BO」を、倉庫は「将来の入荷予定 − 将来の出荷確定分」を在庫ポジションに反映するため、日々の発注量が雪だるま式に増加せず、供給回復時の過大在庫化を抑制します。

## テスト

- 事前準備: 仮想環境で依存関係をインストール（`pip install -r requirements.txt`）。
- 実行: `bash scripts/test.sh`

検証内容
- PSI恒等: `demand = sales + shortage`
- 在庫フロー: `end = start + incoming + produced − sales − consumption`
- 累積整合: `合計発注 = 合計受入 + 期末輸送中`
- 発注制約: ノード/リンクの `MOQ` と（整数の）`order_multiple` 満足
- BO誘発下の安定性: リードタイム内の連日発注が単調非増加（雪だるま抑制）

### CI（GitHub Actions）

- 本リポジトリには GitHub Actions のワークフロー（`.github/workflows/ci.yml`）を用意しています。
- すべてのブランチへの push / PR で以下を自動実行します。
  - Python 3.12 セットアップ
  - `pip install -r requirements.txt`
  - `python -m unittest discover` によるユニットテスト
