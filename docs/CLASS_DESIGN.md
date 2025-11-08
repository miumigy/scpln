# Class Design Guide (SimulationInput family)

This document outlines the class structure for simulation input models and core engine components. The domain layer (`domain/models.py`) is the anchor, and engine usage patterns are described alongside it.

## Domain models (Pydantic)

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

### AnyNode discriminated union

`AnyNode` is a discriminated union (`Field(discriminator="node_type")`) that expands to `StoreNode`, `WarehouseNode`, `MaterialNode`, or `FactoryNode`. JSON payloads select the appropriate class based on `node_type`.

## Engine usage overview

```mermaid
sequenceDiagram
    participant UI as Planning Hub UI
    participant API as FastAPI /plans
    participant Domain as domain.models
    participant Engine as engine.simulator

    UI->>API: POST /plans/integrated/run
    API->>Domain: SimulationInput.parse_obj(payload)
    Domain-->>API: SimulationInput instance
    API->>Engine: SupplyChainSimulator(simulation_input)
    Engine->>Engine: run() / day-by-day PSI
    Engine-->>API: results, plan artifacts
    API-->>UI: version_id, artifacts summary
```

## Extension guidelines

- To add new node types, inherit from `BaseNode`, assign a unique `node_type`, and include the class in the `AnyNode` union.
- When extending engine logic, either maintain `SimulationInput` schema compatibility or bump `schema_version` and implement compatibility handlers.
- The planning pipeline (aggregate / allocate / mrp / reconcile) exchanges JSON artifacts using the models above. Confirm consistency with `docs/AGG_DET_RECONCILIATION.md` when changing structures.

## Transaction model (Plan / Run)

Plans and runs are the core transactional entities that track simulation outputs, planning data, and operational history. They are persisted across multiple SQLite tables.

### Class diagram

```mermaid
classDiagram
    class PlanVersion {
        +str version_id
        +str status
        +int created_at
        +int config_version_id
        +int base_scenario_id
        +str objective
        +str note
        +str cutover_date
        +int recon_window_days
    }

    class PlanArtifact {
        +str version_id
        +str name
        +str content
        +int created_at
    }

    class PlanSeriesRow {
        +str version_id
        +str level
        +str time_bucket_type
        +str time_bucket_key
        +str item_key
        +str location_key
        +float demand
        +float supply
        +float backlog
        +float inventory_open
        +float inventory_close
        +float prod_qty
        +float ship_qty
        +float capacity_used
        +float cost_total
        +float service_level
    }

    class PlanKpiRow {
        +str version_id
        +str metric
        +str bucket_type
        +str bucket_key
        +float value
        +str unit
    }

    class PlanOverrideRow {
        +str version_id
        +str level
        +str key_hash
        +str payload_json
        +bool lock_flag
        +str locked_by
        +float weight
        +str author
        +str source
    }

    class PlanOverrideEventRow {
        +int override_id
        +str version_id
        +str level
        +str key_hash
        +str event_type
        +int event_ts
        +str payload_json
        +str actor
        +str notes
    }

    class PlanJobRow {
        +str job_id
        +str version_id
        +str status
        +int submitted_at
        +int started_at
        +int finished_at
        +int duration_ms
        +str error
        +str payload_json
    }

    class Run {
        +str run_id
        +str status
        +int created_at
        +int config_version_id
        +int scenario_id
        +str plan_version_id
        +str trigger
        +str note
    }

    class RunArtifact {
        +str run_id
        +str name
        +str content
        +int created_at
    }

    PlanVersion "1" -- "0..*" PlanArtifact : contains
    PlanVersion "1" -- "0..*" PlanSeriesRow : generates
    PlanVersion "1" -- "0..*" PlanKpiRow : generates
    PlanVersion "1" -- "0..*" PlanOverrideRow : has
    PlanVersion "1" -- "0..*" PlanOverrideEventRow : logs
    PlanVersion "1" -- "0..*" PlanJobRow : manages
    Run "1" -- "0..*" RunArtifact : contains
    Run "1" -- "0..1" PlanVersion : creates
```

### Entity descriptions

#### PlanVersion
Metadata for managing plan versions:
- `version_id`: unique plan ID.
- `status`: current state (e.g., active, archived).
- `created_at`: UNIX timestamp.
- `config_version_id`: configuration version used.
- `base_scenario_id`: originating scenario ID.
- `objective`: plan objective.
- `note`: free-form memo.
- `cutover_date`: cutover date.
- `recon_window_days`: reconciliation window in days.

#### PlanArtifact
Stores detailed data (JSON, etc.) linked to a plan version:
- `version_id`: associated plan ID.
- `name`: artifact name (e.g., `aggregate.json`, `sku_week.json`).
- `content`: serialized artifact content.
- `created_at`: timestamp.

#### PlanSeriesRow
Holds time-series planning data (PSI metrics):
- `version_id`: associated plan ID.
- `level`: aggregation level (e.g., aggregate, det).
- `time_bucket_type`: bucket type (week, month, etc.).
- `time_bucket_key`: bucket key (e.g., `2023-W01`, `2023-01`).
- `item_key`: item identifier.
- `location_key`: location identifier.
- `demand`: demand quantity.
- `supply`: supply quantity.
- `backlog`: backlog quantity.
- `inventory_open`: opening inventory.
- `inventory_close`: closing inventory.
- `prod_qty`: production quantity.
- `ship_qty`: shipment quantity.
- `capacity_used`: utilized capacity.
- `cost_total`: total cost.
- `service_level`: service level.

#### PlanKpiRow
Stores KPIs for a plan:
- `version_id`: associated plan ID.
- `metric`: KPI name (e.g., `total_cost`, `service_level_avg`).
- `bucket_type`: aggregation bucket type.
- `bucket_key`: aggregation bucket key.
- `value`: KPI value.
- `unit`: KPI unit.

#### PlanOverrideRow
Represents the current state of manual overrides:
- `version_id`: associated plan ID.
- `level`: override level (aggregate, det, etc.).
- `key_hash`: hash identifying the override target.
- `payload_json`: override payload.
- `lock_flag`: whether the override is locked.
- `locked_by`: user who locked it.
- `weight`: weight used for allocation logic.
- `author`: override creator.
- `source`: origin of the override.

#### PlanOverrideEventRow
Audit log for manual overrides:
- `override_id`: ID of the related `PlanOverrideRow`.
- `version_id`: associated plan ID.
- `level`: event level.
- `key_hash`: target hash.
- `event_type`: event type (e.g., edit, lock, unlock).
- `event_ts`: event timestamp (UNIX).
- `payload_json`: detailed payload.
- `actor`: user who performed the event.
- `notes`: additional notes.

#### PlanJobRow
Metadata for plan execution jobs:
- `job_id`: unique job ID.
- `version_id`: associated plan ID.
- `status`: job status (pending, running, completed, failed, etc.).
- `submitted_at`: submission timestamp.
- `started_at`: start timestamp.
- `finished_at`: finish timestamp.
- `duration_ms`: runtime in milliseconds.
- `error`: error message.
- `payload_json`: job payload.

#### Run
Metadata for simulations:
- `run_id`: unique run ID.
- `status`: current state.
- `created_at`: creation timestamp.
- `config_version_id`: configuration version used.
- `scenario_id`: scenario ID used.
- `plan_version_id`: plan version produced by the run.
- `trigger`: execution trigger.
- `note`: run memo.

#### RunArtifact
Stores artifacts related to a run:
- `run_id`: associated run ID.
- `name`: artifact name.
- `content`: artifact content.
- `created_at`: timestamp.
