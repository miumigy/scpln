from domain.models import (
    SimulationInput,
    Product,
    FactoryNode,
    WarehouseNode,
    StoreNode,
    NetworkLink,
    CustomerDemand,
)
from engine.simulator import SupplyChainSimulator


def _payload_production_over(days: int = 2) -> SimulationInput:
    # 工場→倉庫→店舗の1ライン。店舗需要が大きく、工場の生産キャパを超える量を生産。
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="FG", sales_price=0.0)],
        nodes=[
            FactoryNode(
                name="F1",
                producible_products=["FG"],
                production_capacity=10.0,
                production_cost_fixed=5.0,
                allow_production_over_capacity=True,
                production_over_capacity_fixed_cost=4.0,
                production_over_capacity_variable_cost=2.0,
            ),
            WarehouseNode(name="W1"),
            StoreNode(name="S1"),
        ],
        network=[
            NetworkLink(
                from_node="F1",
                to_node="W1",
                transportation_cost_fixed=0.0,
                transportation_cost_variable=0.0,
                lead_time=0,
            ),
            NetworkLink(
                from_node="W1",
                to_node="S1",
                transportation_cost_fixed=0.0,
                transportation_cost_variable=0.0,
                lead_time=0,
            ),
        ],
        customer_demand=[
            CustomerDemand(store_name="S1", product_name="FG", demand_mean=80.0, demand_std_dev=0.0)
        ],
        random_seed=42,
    )


def test_recomputed_pl_length_and_assertion_production_over():
    sim = SupplyChainSimulator(_payload_production_over(days=2))
    _results, _pl = sim.run()

    # 再集計の長さ
    trace_daily = sim.recompute_pl_from_trace()
    assert len(trace_daily) == sim.input.planning_horizon

    # 整合性アサート（例外なしで通過すること）
    sim.assert_pl_equals_trace_totals()

