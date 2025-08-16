from domain.models import (
    SimulationInput,
    Product,
    WarehouseNode,
    StoreNode,
    NetworkLink,
    CustomerDemand,
)
from engine.simulator import SupplyChainSimulator


def _payload_storage_overage(days: int = 2) -> SimulationInput:
    return SimulationInput(
        planning_horizon=days,
        products=[Product(name="FG", sales_price=0.0)],
        nodes=[
            WarehouseNode(name="W1", initial_stock={"FG": 200}),
            StoreNode(
                name="S1",
                initial_stock={"FG": 0},
                storage_capacity=5.0,
                allow_storage_over_capacity=True,
                storage_over_capacity_fixed_cost=3.0,
                storage_over_capacity_variable_cost=1.5,
            ),
        ],
        network=[
            NetworkLink(
                from_node="W1",
                to_node="S1",
                transportation_cost_fixed=0.0,
                transportation_cost_variable=0.0,
                capacity_per_day=1000.0,
                allow_over_capacity=True,
                lead_time=0,
            ),
        ],
        customer_demand=[
            CustomerDemand(store_name="S1", product_name="FG", demand_mean=30.0, demand_std_dev=0.0)
        ],
        random_seed=7,
    )


def test_recomputed_pl_length_and_assertion_storage_overage():
    sim = SupplyChainSimulator(_payload_storage_overage(days=2))
    _results, _pl = sim.run()
    trace_daily = sim.recompute_pl_from_trace()
    assert len(trace_daily) == sim.input.planning_horizon
    sim.assert_pl_equals_trace_totals()

