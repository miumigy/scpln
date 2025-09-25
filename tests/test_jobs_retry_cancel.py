import importlib
import time
from fastapi.testclient import TestClient

importlib.import_module("app.jobs_api")

from app.api import app
from domain.models import SimulationInput, Product, StoreNode, CustomerDemand


def _payload():
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 0})],
        network=[],
        customer_demand=[
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=0, demand_std_dev=0
            )
        ],
        random_seed=1,
    )


def test_job_retry_with_new_params(db_setup):
    c = TestClient(app)
    # enqueue invalid job to fail (empty dict)
    jid = c.post("/jobs/simulation", json={}).json()["job_id"]
    # wait fail
    for _ in range(50):
        st = c.get(f"/jobs/{jid}").json()["status"]
        if st == "failed":
            break
        time.sleep(0.05)
    assert c.get(f"/jobs/{jid}").json()["status"] == "failed"
    # retry with valid params
    r = c.post(f"/jobs/{jid}/retry", json={"params": _payload().model_dump()})
    assert r.status_code == 200
    # wait succeed
    for _ in range(50):
        body = c.get(f"/jobs/{jid}").json()
        if body["status"] == "succeeded":
            assert body.get("run_id")
            break
        time.sleep(0.05)
    assert c.get(f"/jobs/{jid}").json()["status"] == "succeeded"


def test_job_cancel_best_effort(db_setup):
    c = TestClient(app)
    jid = c.post("/jobs/simulation", json=_payload().model_dump()).json()["job_id"]
    # try cancel; accept 200 or 409 depending on race (queued vs running)
    r = c.post(f"/jobs/{jid}/cancel")
    assert r.status_code in (200, 409)
