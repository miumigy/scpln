from collections import defaultdict
from domain.models import (
    SimulationInput,
    Product,
    StoreNode,
    CustomerDemand,
)
from engine.simulator import SupplyChainSimulator


def _payload_store_only(days=2):
    # ストア単独（上流なし）で、保管コスト & 欠品/BOペナが必ず出る最小構成
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="P1", sales_price=100.0)],
        nodes=[
            StoreNode(
                name="S1",
                initial_stock={"P1": 10},  # 在庫あり → storage_var/固定が出る
                storage_cost_fixed=3.0,  # 固定
                storage_cost_variable={"P1": 1.0},  # 変動(在庫×1.0)
                backorder_enabled=True,  # BOを積む
                lost_sales=False,
                stockout_cost_per_unit=2.0,  # 欠品ペナ
                backorder_cost_per_unit_per_day=0.5,  # BOキャリー
            ),
        ],
        network=[],  # 上流がないので補充は来ない
        customer_demand=[
            CustomerDemand(
                store_name="S1", product_name="P1", demand_mean=20.0, demand_std_dev=0.0
            )
        ],
        random_seed=1,
    )


def test_trace_has_storage_and_penalties_events():
    sim = SupplyChainSimulator(_payload_store_only(days=2))
    results, pl = sim.run()

    # Trace を event/account ごとに集計
    has = set((e["event"], e["account"]) for e in sim.cost_trace)

    # 保管（固定・変動）、欠品、BO の各イベントが少なくとも1回は記録されていること
    assert ("storage_fixed", "storage_fixed") in has
    assert ("storage_var", "storage_var") in has
    assert ("penalty_stockout", "penalty_stockout") in has
    assert ("penalty_backorder", "penalty_backorder") in has


def test_trace_amounts_match_pl_components_for_store_storage_and_penalties():
    # 2日で回す（在庫もBOも継続するため、日次合計が出やすい）
    sim = SupplyChainSimulator(_payload_store_only(days=2))
    results, daily_pl_list = sim.run()

    # Trace 側集計
    agg = defaultdict(float)
    for e in sim.cost_trace:
        agg[e["account"]] += e["amount"]

    # PL 側集計（Store ノードのみを使っているので、対応カテゴリは store_*）
    total_store_storage_fixed = sum(
        pl["stock_costs"]["store_storage_fixed"] for pl in daily_pl_list
    )
    total_store_storage_var = sum(
        pl["stock_costs"]["store_storage_variable"] for pl in daily_pl_list
    )
    total_penalty_stockout = sum(
        pl["penalty_costs"]["stockout"] for pl in daily_pl_list
    )
    total_penalty_backorder = sum(
        pl["penalty_costs"]["backorder"] for pl in daily_pl_list
    )

    # 誤差は浮動小数で1e-6程度
    assert abs(agg["storage_fixed"] - total_store_storage_fixed) < 1e-6
    assert abs(agg["storage_var"] - total_store_storage_var) < 1e-6
    assert abs(agg["penalty_stockout"] - total_penalty_stockout) < 1e-6
    assert abs(agg["penalty_backorder"] - total_penalty_backorder) < 1e-6
