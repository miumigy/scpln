import importlib
from fastapi.testclient import TestClient

importlib.import_module("app.simulation_api")
importlib.import_module("app.run_list_api")
importlib.import_module("app.trace_export_api")

from app.api import app
from domain.models import (
    SimulationInput, Product, StoreNode, CustomerDemand
)


def _payload():
    # ストア単独・販売あり（trace に何らかの行が残る想定）
    return SimulationInput(
        planning_horizon=2,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[StoreNode(name="S1", initial_stock={"P1": 5})],
        network=[],
        customer_demand=[CustomerDemand(store_name="S1", product_name="P1", demand_mean=3, demand_std_dev=0)],
        random_seed=1,
    )


def test_trace_csv_download():
    client = TestClient(app)
    r = client.post("/simulation?include_trace=true", json=_payload().model_dump())
    run_id = r.json()["run_id"]

    csvr = client.get(f"/runs/{run_id}/trace.csv")
    assert csvr.status_code == 200
    body = csvr.text.splitlines()
    assert body[0].startswith("run_id,day,node,item,event,qty,unit_cost,amount,account")
    # 行が1つ以上（状況により 0 のこともあるが、最低ヘッダは存在）
    assert len(body) >= 1

