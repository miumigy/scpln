from collections import defaultdict
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
from engine.simulator import SupplyChainSimulator


def _payload_force_production(days=2):
    """
    工場のキャパを超える生産が必ず起きる最小チェーン。
    Factory の over-capacity 固定/変動コストを発生させる。
    """
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            # 原材料（コストはゼロでもOK。ここではゼロにして生産コストの検証に集中）
            MaterialNode(name="M1", initial_stock={"P1": 0}, material_cost={"P1": 0.0}),
            # 工場：P1を生産。キャパを小さく、オーバー固定/変動を設定
            FactoryNode(
                name="F1",
                producible_products=["P1"],
                initial_stock={"P1": 0},
                production_capacity=10,  # 小さいキャパ
                production_cost_fixed=40.0,  # 生産があれば/日1回の固定費
                production_cost_variable=0.0,  # 基本の変動費は使わない
                allow_production_over_capacity=True,
                production_over_capacity_fixed_cost=25.0,  # オーバー固定費
                production_over_capacity_variable_cost=2.0,  # オーバー変動（数量比例）
            ),
            # 倉庫と店舗：需要は店舗のみで発生（大きめにして工場生産を誘発）
            WarehouseNode(name="W1", initial_stock={"P1": 0}),
            StoreNode(name="S1", initial_stock={"P1": 0}),
        ],
        network=[
            # リンクは在庫/需要伝播のために必要（コスト0でOK）
            NetworkLink(from_node="M1", to_node="F1", lead_time=0),
            NetworkLink(from_node="F1", to_node="W1", lead_time=0),
            NetworkLink(from_node="W1", to_node="S1", lead_time=0),
        ],
        customer_demand=[
            # 大きな需要で工場の生産量をキャパ超へ
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=80.0, demand_std_dev=0.0
            )
        ],
        random_seed=1,
    )


def test_production_fixed_and_overage_events_exist():
    sim = SupplyChainSimulator(_payload_force_production(days=2))
    results, daily_pl = sim.run()

    events = set((e["event"], e["account"]) for e in sim.cost_trace)

    # 生産固定費（生産があった日）
    assert ("production_fixed", "production_fixed") in events

    # キャパ超過が起きるので、固定/変動のいずれか（または両方）が発生しているはず
    assert ("production_over_fixed", "production_fixed") in events or (
        "production_over_var",
        "production_var",
    ) in events


def test_trace_matches_pl_for_production_costs():
    sim = SupplyChainSimulator(_payload_force_production(days=2))
    results, daily_pl_list = sim.run()

    # Trace 側の科目別合計
    agg = defaultdict(float)
    for e in sim.cost_trace:
        agg[e["account"]] += e["amount"]

    # PL 側の対象科目（flow_costs）
    total_fixed = sum(pl["flow_costs"]["production_fixed"] for pl in daily_pl_list)
    total_var = sum(pl["flow_costs"]["production_variable"] for pl in daily_pl_list)

    # 誤差は浮動小数の丸めに配慮
    assert abs(agg["production_fixed"] - total_fixed) < 1e-6
    assert abs(agg["production_var"] - total_var) < 1e-6
