import re
import importlib
from fastapi.testclient import TestClient

# 先に副作用 import で /simulation を登録
importlib.import_module("app.simulation_api")

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

UUID4_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
    re.IGNORECASE,
)

def _minimal_payload():
    # もっとも単純な 1 製品チェーン（需要ゼロ）: API の疎通検証用
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            MaterialNode(name="M1", node_type="material", initial_stock={"P1": 0}, material_cost={"P1": 0.0}, storage_capacity=1e18),
            FactoryNode(name="F1", node_type="factory", producible_products=["P1"], initial_stock={"P1": 0}, storage_capacity=1e18),
            WarehouseNode(name="W1", node_type="warehouse", initial_stock={"P1": 0}, storage_capacity=1e18),
            StoreNode(name="S1", node_type="store", initial_stock={"P1": 0}, storage_capacity=1e18),
        ],
        network=[
            NetworkLink(from_node="M1", to_node="F1", lead_time=0, capacity_per_day=1e18),
            NetworkLink(from_node="F1", to_node="W1", lead_time=0, capacity_per_day=1e18),
            NetworkLink(from_node="W1", to_node="S1", lead_time=0, capacity_per_day=1e18),
        ],
        customer_demand=[
            CustomerDemand(store_name="S1", product_name="P1", demand_mean=0.0, demand_std_dev=0.0)
        ],
        random_seed=1,
    )

def test_simulation_endpoint_runs_and_returns_run_id_without_trace_by_default():
    client = TestClient(app)
    payload = _minimal_payload().model_dump(mode='json')
    r = client.post("/simulation", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    # run_id が UUID4
    assert "run_id" in body
    assert UUID4_RE.match(body["run_id"])
    # 既定は include_trace=false なので cost_trace は無い or 空
    assert "cost_trace" not in body or body["cost_trace"] in ([], None)
    # 結果の基本形が返る
    assert isinstance(body.get("results"), list)
    assert isinstance(body.get("daily_profit_loss"), list)

def test_simulation_endpoint_returns_trace_when_requested():
    client = TestClient(app)
    payload = _minimal_payload().model_dump(mode='json')
    r = client.post("/simulation?include_trace=true", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "run_id" in body and UUID4_RE.match(body["run_id"])
    # トレースが配列であること
    assert "cost_trace" in body
    assert isinstance(body["cost_trace"], list)

def test_run_id_changes_each_call():
    client = TestClient(app)
    payload = _minimal_payload().model_dump(mode='json')
    r1 = client.post("/simulation", json=payload)
    r2 = client.post("/simulation", json=payload)
    id1 = r1.json()["run_id"]
    id2 = r2.json()["run_id"]
    assert id1 != id2
    assert UUID4_RE.match(id1) and UUID4_RE.match(id2)
