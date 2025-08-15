# tests/test_schema_version.py
from domain.models import (
    SimulationInput,
    Product,
    MaterialNode,
    FactoryNode,
    WarehouseNode,
    StoreNode,
    NetworkLink,
    CustomerDemand,
)

def _minimal_payload():
    # SimulationInput を生成できる最小セット（シミュレーションは回さない）
    return dict(
        planning_horizon=3,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            MaterialNode(name="M1", initial_stock={"P1": 0}, material_cost={"P1": 20.0}),
            FactoryNode(name="F1", producible_products=["P1"], initial_stock={"P1": 0}),
            WarehouseNode(name="W1", initial_stock={"P1": 0}),
            StoreNode(name="S1", initial_stock={"P1": 0}),
        ],
        network=[
            NetworkLink(from_node="M1", to_node="F1"),
            NetworkLink(from_node="F1", to_node="W1"),
            NetworkLink(from_node="W1", to_node="S1"),
        ],
        customer_demand=[
            CustomerDemand(store_name="S1", product_name="P1", demand_mean=0.0, demand_std_dev=0.0)
        ],
        random_seed=1,
    )

def test_schema_version_default_is_1_0():
    payload = _minimal_payload()
    # schema_version を渡さない（後方互換）
    si = SimulationInput(**payload)
    assert hasattr(si, "schema_version")
    assert si.schema_version == "1.0"

def test_schema_version_can_be_overridden():
    payload = _minimal_payload()
    payload["schema_version"] = "1.1"
    si = SimulationInput(**payload)
    assert si.schema_version == "1.1"
