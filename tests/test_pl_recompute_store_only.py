from domain.models import (
    SimulationInput,
    Product,
    StoreNode,
    CustomerDemand,
)
from engine.simulator import SupplyChainSimulator


def _payload_store_only(days: int = 3) -> SimulationInput:
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="P1", sales_price=0.0)],
        nodes=[
            StoreNode(
                name="S1",
                initial_stock={"P1": 5},
                storage_cost_fixed=2.0,
                storage_cost_variable={"P1": 1.0},
                backorder_enabled=True,
                lost_sales=False,
                stockout_cost_per_unit=3.0,
                backorder_cost_per_unit_per_day=1.0,
            )
        ],
        network=[],
        customer_demand=[
            CustomerDemand(
                store_name="S1",
                product_name="P1",
                demand_mean=10.0,
                demand_std_dev=0.0,
            )
        ],
        random_seed=123,
    )


def test_recomputed_pl_length_and_assertion_store_only():
    sim = SupplyChainSimulator(_payload_store_only(days=3))
    _results, _pl = sim.run()

    trace_daily = sim.recompute_pl_from_trace()
    assert len(trace_daily) == sim.input.planning_horizon

    # 整合性アサート（例外なしで通過すること）
    sim.assert_pl_equals_trace_totals()
