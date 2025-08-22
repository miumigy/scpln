import importlib
import time
from fastapi.testclient import TestClient

importlib.import_module("app.jobs_api")
importlib.import_module("app.simulation_api")

from app.api import app
from domain.models import SimulationInput, Product, StoreNode, CustomerDemand


def _payload():
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 0})],
        network=[],
        customer_demand=[CustomerDemand(store_name="S1", product_name="P1", demand_mean=0, demand_std_dev=0)],
        random_seed=1,
    )


def test_jobs_simulation_end_to_end():
    client = TestClient(app)
    # enqueue
    r = client.post("/jobs/simulation", json=_payload().model_dump())
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    # poll
    status = None
    for _ in range(50):
        g = client.get(f"/jobs/{job_id}")
        assert g.status_code == 200
        body = g.json()
        status = body["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert status == "succeeded"
    assert body.get("run_id")

