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


def test_runs_filter_by_scenario_id():
    client = TestClient(app)
    r1 = client.post("/simulation?scenario_id=101", json=_payload(0).model_dump())
    r2 = client.post("/simulation?scenario_id=202", json=_payload(5).model_dump())
    assert r1.status_code == 200 and r2.status_code == 200

    lr_all = client.get("/runs?limit=100")
    assert lr_all.status_code == 200
    runs_all = lr_all.json()["runs"]
    assert any(x.get("schema_version") for x in runs_all)

    lr_101 = client.get("/runs?scenario_id=101&limit=100")
    assert lr_101.status_code == 200
    runs_101 = lr_101.json()["runs"]
    # 全件のうち、scenario_id=101 のみが含まれる
    assert all(
        (x.get("scenario_id") == 101)
        for x in runs_101
        if x.get("scenario_id") is not None
    )
