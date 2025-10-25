import pytest

from domain.models import CustomerDemand, Product, SimulationInput, StoreNode
from engine.simulator import SupplyChainSimulator


def test_store_sales_record_cost_of_goods():
    product = Product(name="P1", sales_price=200.0, unit_cost=80.0)
    store = StoreNode(name="S1", initial_stock={"P1": 100}, lead_time=0)
    demand = CustomerDemand(
        store_name="S1",
        product_name="P1",
        demand_mean=10.0,
        demand_std_dev=0.0,
    )

    sim_input = SimulationInput(
        planning_horizon=5,
        products=[product],
        nodes=[store],
        network=[],
        customer_demand=[demand],
        random_seed=1,
    )

    sim = SupplyChainSimulator(sim_input)
    _results, daily_pl = sim.run()

    total_material_cost = sum(pl.get("material_cost", 0.0) for pl in daily_pl)
    assert total_material_cost == pytest.approx(5 * 10.0 * 80.0)

    assert any(evt.get("event") == "sale_cogs" for evt in sim.cost_trace)
