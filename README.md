# サプライチェーン計画シミュレーション

このプロジェクトは、部品表 (BOM) をサポートし、在庫補充ポリシーに基づいたサプライチェーンシミュレーションを提供します。需要の伝播、工場での生産と材料消費、リードタイムを考慮した在庫管理をシミュレートし、日ごとの詳細な結果を可視化します。

## 機能

*   **柔軟なシミュレーション入力**: 製品の部品構成表 (BOM)、ノード（店舗、倉庫、工場、サプライヤー）、ネットワーク接続、顧客需要をJSON形式で柔軟に定義できます。
*   **在庫補充ポリシー**: 各ノードは、サービスレベルに応じて設定された発注点 (`reorder_point`) と目標在庫レベル (`order_up_to_level`) に基づいて、自動的に上流ノードへ発注を行います。最小発注量 (`moq`) も考慮されます。
*   **需要の伝播と在庫管理**: 下流ノードで発生した需要（顧客需要や発注）は、サプライチェーンを遡って上流ノードの需要として適切に伝播されます。
*   **リードタイムの考慮**: 発注から入荷までのリードタイムがシミュレーションに反映され、輸送中の在庫が管理されます。
*   **詳細な日次シミュレーション結果の表形式表示**: シミュレーション結果は、日ごとの各ノード・各品目に関する詳細な指標が表形式で表示されます。
*   **収支機能**: 各ノードの保管費用、フローコスト（材料原価、生産、輸送）を固定費・変動費に分けて計算し、日別の収支表を表示します。
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
        { "name": "店舗1", "node_type": "store", "initial_stock": { "完成品A": 30 }, "service_level": 0.95, "storage_cost_fixed": 100, "storage_cost_variable": {"完成品A": 0.5}, "backorder_enabled": true },
        { "name": "中央倉庫", "node_type": "warehouse", "initial_stock": { "完成品A": 100 }, "service_level": 0.90, "storage_cost_fixed": 500, "storage_cost_variable": {"完成品A": 0.2}, "backorder_enabled": true },
        { "name": "組立工場", "node_type": "factory", "producible_products": ["完成品A"], "initial_stock": { "完成品A": 50, "材料X": 500, "材料Y": 800 }, "lead_time": 14, "production_capacity": 50, "production_cost_fixed": 10000, "production_cost_variable": 50, "storage_cost_fixed": 1000, "storage_cost_variable": {"完成品A": 0.3, "材料X": 0.1, "材料Y": 0.1}, "backorder_enabled": true },
        { "name": "サプライヤーX", "node_type": "material", "initial_stock": { "材料X": 10000 }, "material_cost": {"材料X": 100}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料X": 0.01}, "backorder_enabled": true },
        { "name": "サプライヤーY", "node_type": "material", "initial_stock": { "材料Y": 10000 }, "material_cost": {"材料Y": 20}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料Y": 0.01}, "backorder_enabled": true }
    ],
    "network": [
        { "from_node": "中央倉庫", "to_node": "店舗1", "transportation_cost_fixed": 200, "transportation_cost_variable": 3, "lead_time": 3 },
        { "from_node": "組立工場", "to_node": "中央倉庫", "transportation_cost_fixed": 500, "transportation_cost_variable": 2, "lead_time": 7 },
        { "from_node": "サプライヤーX", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 30 },
        { "from_node": "サプライヤーY", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 20 }
    ],
    "customer_demand": [
        { "store_name": "店舗1", "product_name": "完成品A", "demand_mean": 15, "demand_std_dev": 2 }
    ]
}
```

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
