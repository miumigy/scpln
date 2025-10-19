import re
import importlib

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.run_registry import REGISTRY
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

# /simulation を有効化
importlib.import_module("app.simulation_api")

pytestmark = pytest.mark.slow

UUID4_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
    re.IGNORECASE,
)


def _payload():
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
                store_name="S1", product_name="P1", demand_mean=0, demand_std_dev=0
            )
        ],
        random_seed=1,
    )


def test_run_id_and_registry_put():
    client = TestClient(app)
    r = client.post("/simulation", json=_payload().model_dump())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "run_id" in body and UUID4_RE.match(body["run_id"])
    # registry に入っている
    rec = REGISTRY.get(body["run_id"])
    assert rec and rec["run_id"] == body["run_id"]
    assert "results" in rec and "daily_profit_loss" in rec
