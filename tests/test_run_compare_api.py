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

# /simulation と /compare のAPIを副作用importで登録
importlib.import_module("app.simulation_api")
importlib.import_module("app.run_compare_api")

pytestmark = pytest.mark.slow


def _payload(fill_rate_bias: float, days=3):
    # fill_rate を意図的に変えるため、需要量にバイアスを掛ける
    dm = max(0.0, 20.0 * fill_rate_bias)
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            MaterialNode(
                name="M1",
                initial_stock={"P1": 0},
                material_cost={"P1": 0.0},
                storage_capacity=1e18,
            ),
            FactoryNode(
                name="F1",
                producible_products=["P1"],
                initial_stock={"P1": 0},
                storage_capacity=1e18,
            ),
            WarehouseNode(name="W1", initial_stock={"P1": 0}, storage_capacity=1e18),
            StoreNode(name="S1", initial_stock={"P1": 0}, storage_capacity=1e18),
        ],
        network=[
            NetworkLink(
                from_node="M1", to_node="F1", lead_time=0, capacity_per_day=1e18
            ),
            NetworkLink(
                from_node="F1", to_node="W1", lead_time=0, capacity_per_day=1e18
            ),
            NetworkLink(
                from_node="W1", to_node="S1", lead_time=0, capacity_per_day=1e18
            ),
        ],
        customer_demand=[
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=dm, demand_std_dev=0.0
            )
        ],
        random_seed=1,
    )


def test_runs_registry_and_compare():
    client = TestClient(app)

    # run 1: 需要少なめ
    r1 = client.post("/simulation", json=_payload(fill_rate_bias=0.2).model_dump())
    assert r1.status_code == 200, r1.text
    run1 = r1.json()["run_id"]

    # run 2: 需要多め（fill rate やコストが変わるはず）
    r2 = client.post("/simulation", json=_payload(fill_rate_bias=1.0).model_dump())
    assert r2.status_code == 200, r2.text
    run2 = r2.json()["run_id"]

    # /runs 一覧
    lr = client.get("/runs")
    assert lr.status_code == 200
    runs = lr.json()["runs"]
    ids = [r["run_id"] for r in runs]
    assert run1 in ids and run2 in ids

    # /runs/{id} 単独取得
    g1 = client.get(f"/runs/{run1}")
    assert g1.status_code == 200
    s1 = g1.json()
    assert "summary" in s1 and isinstance(s1["summary"], dict)

    # /compare
    comp = client.post("/compare", json={"run_ids": [run1, run2]})
    assert comp.status_code == 200, comp.text
    body = comp.json()
    # metrics: 2行（run1, run2）で、主要キーを含む
    assert len(body["metrics"]) == 2
    for row in body["metrics"]:
        for k in ["fill_rate", "cost_total", "profit_total"]:
            assert k in row
    # diffs: 1件（run1→run2）
    assert len(body["diffs"]) == 1
    d0 = body["diffs"][0]
    assert d0["base"] == run1 and d0["target"] == run2
    # 差分に abs/pct が入っている
    assert "fill_rate" in d0 and "abs" in d0["fill_rate"]
