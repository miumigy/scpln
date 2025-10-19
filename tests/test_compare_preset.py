import importlib

import pytest
from fastapi.testclient import TestClient

from app.api import app
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

importlib.import_module("app.ui_compare")
importlib.import_module("app.simulation_api")
importlib.import_module("app.run_list_api")

pytestmark = pytest.mark.slow


def _payload(dm: float):
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            MaterialNode(name="M1", initial_stock={"P1": 0}, material_cost={"P1": 0.0}),
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
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=dm, demand_std_dev=0
            )
        ],
        random_seed=1,
    )


def test_compare_preset_by_scenarios():
    c = TestClient(app)
    # 2つのシナリオで各1Runを作る
    c.post("/simulation?scenario_id=301", json=_payload(0).model_dump())
    c.post("/simulation?scenario_id=302", json=_payload(5).model_dump())
    r = c.get("/ui/compare/preset?base_scenario=301&target_scenarios=302")
    assert r.status_code == 200
    body = r.text
    assert "Compare" in body
    # ランIDが2つ含まれる（粗い確認）
    assert "Metrics" in body or "Diffs" in body or "run_id" in body
