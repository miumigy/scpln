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

## セットアップ方法

1.  **Pythonのインストール**: Python 3.9以上がインストールされていることを確認してください。
2.  **プロジェクトディレクトリへの移動**: ターミナルでプロジェクトのルートディレクトリに移動します。
    ```bash
    cd /home/miumigy/gemini/scsim
    ```
3.  **仮想環境の作成とアクティブ化**: 依存関係を分離するために仮想環境を使用することを推奨します。
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
4.  **依存関係のインストール**: 必要なライブラリをインストールします。
    ```bash
    pip install fastapi uvicorn pydantic scipy
    ```

## シミュレーションの実行 (Web UI)

1.  **仮想環境のアクティブ化**: まだアクティブ化していない場合は、仮想環境をアクティブ化します。
    ```bash
    source venv/bin/activate
    ```
2.  **Uvicornサーバーの起動**: FastAPIアプリケーションを起動します。
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8000
    ```
    サーバーはバックグラウンドで実行されます。
3.  **ブラウザでのアクセス**: ウェブブラウザで `http://localhost:8000` にアクセスします。
4.  **シミュレーションの実行**: JSONエディタに表示されているサンプル入力を使用するか、独自のシミュレーション定義を貼り付けて「シミュレーション実行」ボタンをクリックします。結果が表形式で表示されます。

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
        { "name": "店舗1", "node_type": "store", "initial_stock": { "完成品A": 30 }, "lead_time": 3, "service_level": 0.95, "storage_cost_fixed": 100, "storage_cost_variable": {"完成品A": 0.5} },
        { "name": "中央倉庫", "node_type": "warehouse", "initial_stock": { "完成品A": 100 }, "lead_time": 7, "service_level": 0.90, "storage_cost_fixed": 500, "storage_cost_variable": {"完成品A": 0.2} },
        { "name": "組立工場", "node_type": "factory", "producible_products": ["完成品A"], "initial_stock": { "完成品A": 50, "材料X": 500, "材料Y": 800 }, "lead_time": 14, "production_capacity": 50, "production_cost_fixed": 10000, "production_cost_variable": 50, "storage_cost_fixed": 1000, "storage_cost_variable": {"完成品A": 0.3, "材料X": 0.1, "材料Y": 0.1} },
        { "name": "サプライヤーX", "node_type": "material", "initial_stock": { "材料X": 10000 }, "lead_time": 30, "material_cost": {"材料X": 100}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料X": 0.01} },
        { "name": "サプライヤーY", "node_type": "material", "initial_stock": { "材料Y": 10000 }, "lead_time": 20, "material_cost": {"材料Y": 20}, "storage_cost_fixed": 20, "storage_cost_variable": {"材料Y": 0.01} }
    ],
    "network": [
        { "from_node": "中央倉庫", "to_node": "店舗1", "transportation_cost_fixed": 200, "transportation_cost_variable": 3 },
        { "from_node": "組立工場", "to_node": "中央倉庫", "transportation_cost_fixed": 500, "transportation_cost_variable": 2 },
        { "from_node": "サプライヤーX", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1 },
        { "from_node": "サプライヤーY", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1 }
    ],
    "customer_demand": [
        { "store_name": "店舗1", "product_name": "完成品A", "demand_mean": 15, "demand_std_dev": 2 }
    ]
}
```

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
*   **End Stock**: その日の終了時点の在庫
*   **Ordered Quantity**: その日に発注された数量

収支表は、以下の詳細なコスト分類で表示されます。

*   **Revenue**
*   **Material Cost**
*   **Flow Costs**
    *   Material Transport (Fixed/Variable)
    *   Production (Fixed/Variable)
    *   Warehouse Transport (Fixed/Variable)
    *   Store Transport (Fixed/Variable)
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
