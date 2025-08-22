import importlib
from fastapi.testclient import TestClient

importlib.import_module("app.simulation_api")
importlib.import_module("app.run_compare_api")

from app.api import app
from domain.models import SimulationInput, Product, StoreNode, CustomerDemand


def _payload(dm: float):
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 0})],
        network=[],
        customer_demand=[CustomerDemand(store_name="S1", product_name="P1", demand_mean=dm, demand_std_dev=0)],
        random_seed=1,
    )


def test_runs_created_updated_present():
    c = TestClient(app)
    c.post("/simulation", json=_payload(0).model_dump())
    r = c.get("/runs")
    body = r.json()
    assert "runs" in body and len(body["runs"]) >= 1
    row = body["runs"][0]
    assert "created_at" in row and "updated_at" in row
    assert isinstance(row["created_at"], int)
    assert isinstance(row["updated_at"], int)

