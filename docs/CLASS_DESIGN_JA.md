# クラス設計ガイド（SimulationInput系）

本ドキュメントは、シミュレーション入力モデルおよび主要なエンジン構成要素のクラス構造を示します。ドメイン層（`domain/models.py`）を基点とし、エンジン層での利用イメージも併記します。

## ドメインモデル（Pydantic）

```mermaid
classDiagram
    class SimulationInput {
        +str schema_version
        +int planning_horizon
        +List~Product~ products
        +List~AnyNode~ nodes
        +List~NetworkLink~ network
        +List~CustomerDemand~ customer_demand
        +Optional~int~ random_seed
    }

    class Product {
        +str name
        +float sales_price
        +List~BomItem~ assembly_bom
    }

    class BomItem {
        +str item_name
        +float quantity_per
    }

    class NetworkLink {
        +str from_node
        +str to_node
        +float transportation_cost_fixed
        +float transportation_cost_variable
        +int lead_time
        +float capacity_per_day
        +bool allow_over_capacity
        +float over_capacity_fixed_cost
        +float over_capacity_variable_cost
        +Dict~str,float~ moq
        +Dict~str,float~ order_multiple
    }

    class BaseNode {
        +str name
        +Dict~str,float~ initial_stock
        +int lead_time
        +Dict~str,float~ storage_cost_variable
        +bool backorder_enabled
        +bool lost_sales
        +int review_period_days
        +float stockout_cost_per_unit
        +float backorder_cost_per_unit_per_day
        +float storage_capacity
        +bool allow_storage_over_capacity
    }

    class StoreNode {
        +float service_level
        +Dict~str,float~ moq
        +Dict~str,float~ order_multiple
    }

    class WarehouseNode {
        +float service_level
        +Dict~str,float~ moq
        +Dict~str,float~ order_multiple
    }

    class MaterialNode {
        +Dict~str,float~ material_cost
    }

    class FactoryNode {
        +List~str~ producible_products
        +float service_level
        +float production_capacity
        +float production_cost_fixed
        +float production_cost_variable
        +Dict~str,float~ reorder_point
        +Dict~str,float~ order_up_to_level
        +Dict~str,float~ moq
        +Dict~str,float~ order_multiple
    }

    class CustomerDemand {
        +str store_name
        +str product_name
        +float demand_mean
        +float demand_std_dev
    }

    BaseNode <|-- StoreNode
    BaseNode <|-- WarehouseNode
    BaseNode <|-- MaterialNode
    BaseNode <|-- FactoryNode
    Product "*" --> "*" BomItem
    SimulationInput "*" --> "*" Product
    SimulationInput "*" --> "*" AnyNode
    SimulationInput "*" --> "*" NetworkLink
    SimulationInput "*" --> "*" CustomerDemand
```

### AnyNode 判別型

`AnyNode` は `StoreNode` / `WarehouseNode` / `MaterialNode` / `FactoryNode` の判別型 (`Field(discriminator="node_type")`) で定義されています。JSON入力では `node_type` に応じて適切なクラスが選択されます。

## エンジン利用イメージ

```mermaid
sequenceDiagram
    participant UI as Planning Hub UI
    participant API as FastAPI /plans
    participant Domain as domain.models
    participant Engine as engine.simulator

    UI->>API: POST /plans/integrated/run
    API->>Domain: SimulationInput.parse_obj(payload)
    Domain-->>API: SimulationInputインスタンス
    API->>Engine: SupplyChainSimulator(simulation_input)
    Engine->>Engine: run() / day-by-day PSI
    Engine-->>API: results, plan artifacts
    API-->>UI: version_id, artifacts summary
```

## 拡張時の指針

- ノード種別を追加する場合は `BaseNode` を継承し `node_type` を固有値で定義、`AnyNode` の Union に追加してください。
- エンジン側で計算ロジックを拡張する際は `SimulationInput` のスキーマ互換を維持するか、`schema_version` を更新し互換コードを実装してください。
- 計画パイプライン（aggregate / allocate / mrp / reconcile）は上記モデルをJSONアーティファクトとしてやり取りします。構造変更時は `docs/AGG_DET_RECONCILIATION_JA.md` との整合を確認してください。
