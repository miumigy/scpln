import importlib

import pytest
from fastapi.testclient import TestClient

from app.api import app
from domain.models import (
    SimulationInput,
    Product,
    StoreNode,
    NetworkLink,
    CustomerDemand,
)

importlib.import_module("app.simulation_api")
importlib.import_module("app.run_compare_api")

pytestmark = pytest.mark.slow


def _payload():
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 0})],
        network=[NetworkLink(from_node="S1", to_node="S1")],
        customer_demand=[
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=0, demand_std_dev=0
            )
        ],
        random_seed=1,
    )


def test_delete_run_api():
    client = TestClient(app)
    # create a run
    rid = client.post("/simulation", json=_payload().model_dump()).json()["run_id"]
    # ensure it exists
    assert client.get(f"/runs/{rid}").status_code == 200
    # delete
    dr = client.delete(f"/runs/{rid}")
    assert dr.status_code == 200
    # now 404
    assert client.get(f"/runs/{rid}").status_code == 404
