import importlib
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


def test_runs_list_and_get():
    client = TestClient(app)
    r1 = client.post("/simulation", json=_payload(0).model_dump())
    r2 = client.post("/simulation", json=_payload(5).model_dump())
    id1 = r1.json()["run_id"]
    id2 = r2.json()["run_id"]

    lr = client.get("/runs")
    assert lr.status_code == 200
    ids = [x["run_id"] for x in lr.json()["runs"]]
    assert id1 in ids and id2 in ids

    g1 = client.get(f"/runs/{id1}")
    assert g1.status_code == 200
    body = g1.json()
    assert body["run_id"] == id1
    assert "summary" in body and isinstance(body["summary"], dict)

    g404 = client.get("/runs/does-not-exist")
    assert g404.status_code == 404
