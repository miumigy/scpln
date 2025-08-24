import importlib
from fastapi.testclient import TestClient

importlib.import_module("app.simulation_api")
importlib.import_module("app.run_compare_api")

from app.api import app
from domain.models import (
    SimulationInput,
    Product,
    StoreNode,
    NetworkLink,
    CustomerDemand,
)


def _payload():
    return SimulationInput(
        planning_horizon=1,
        products=[Product(name="P1", sales_price=1.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 0})],
        network=[NetworkLink(from_node="S1", to_node="S1")],
        customer_demand=[CustomerDemand(store_name="S1", product_name="P1", demand_mean=0, demand_std_dev=0)],
        random_seed=1,
    )


def test_rbac_delete_runs_requires_role(monkeypatch):
    monkeypatch.setenv("RBAC_DELETE_ENABLED", "1")
    monkeypatch.setenv("RBAC_DELETE_ROLES", "planner,admin")
    c = TestClient(app)
    rid = c.post("/simulation", json=_payload().model_dump()).json()["run_id"]
    # no role -> 403
    assert c.delete(f"/runs/{rid}").status_code == 403
    # viewer -> 403
    assert c.delete(f"/runs/{rid}", headers={"X-Role": "viewer"}).status_code == 403
    # planner -> 200
    assert c.delete(f"/runs/{rid}", headers={"X-Role": "planner"}).status_code == 200

