import unittest
from main import SimulationInput, SupplyChainSimulator


class TestPenaltyCosts(unittest.TestCase):
    def test_stockout_and_backorder_penalties(self):
        # Deterministic: store has demand 10, zero stock, SL=0, lost_sales=false => shortage=10 and BO=10
        sim_input = {
            "planning_horizon": 1,
            "products": [{"name": "A", "sales_price": 0, "assembly_bom": []}],
            "nodes": [
                {
                    "name": "S",
                    "node_type": "store",
                    "initial_stock": {"A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                    "lost_sales": False,
                    "stockout_cost_per_unit": 2.0,
                    "backorder_cost_per_unit_per_day": 0.5,
                },
                {
                    "name": "W",
                    "node_type": "warehouse",
                    "initial_stock": {"A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                    "stockout_cost_per_unit": 0.0,
                    "backorder_cost_per_unit_per_day": 0.0,
                },
            ],
            "network": [{"from_node": "W", "to_node": "S", "lead_time": 3}],
            "customer_demand": [
                {
                    "store_name": "S",
                    "product_name": "A",
                    "demand_mean": 10,
                    "demand_std_dev": 0,
                }
            ],
        }
        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        _, pl = sim.run()
        day1 = pl[0]
        penalties = day1.get("penalty_costs", {})
        # Stockout penalty = 10 * 2.0 = 20
        # Backorder carrying (end of day) = 10 * 0.5 = 5
        self.assertAlmostEqual(penalties.get("stockout", 0), 20.0)
        self.assertAlmostEqual(penalties.get("backorder", 0), 5.0)
        # Ensure total_cost includes penalties
        flow = sum(day1.get("flow_costs", {}).values())
        stock = sum(day1.get("stock_costs", {}).values())
        mat = day1.get("material_cost", 0)
        expected_total = mat + flow + stock + 25.0
        self.assertAlmostEqual(day1.get("total_cost", 0), expected_total)

    def test_penalty_in_summary(self):
        sim_input = {
            "planning_horizon": 1,
            "products": [{"name": "A", "sales_price": 0, "assembly_bom": []}],
            "nodes": [
                {
                    "name": "S",
                    "node_type": "store",
                    "initial_stock": {"A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                    "lost_sales": False,
                    "stockout_cost_per_unit": 3.0,
                    "backorder_cost_per_unit_per_day": 2.0,
                },
                {
                    "name": "W",
                    "node_type": "warehouse",
                    "initial_stock": {"A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
            ],
            "network": [{"from_node": "W", "to_node": "S", "lead_time": 3}],
            "customer_demand": [
                {
                    "store_name": "S",
                    "product_name": "A",
                    "demand_mean": 5,
                    "demand_std_dev": 0,
                }
            ],
        }
        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()
        summary = sim.compute_summary()
        # shortage=5 -> stockout=15, backorder end-of-day=5 -> backorder=10
        self.assertAlmostEqual(summary.get("penalty_stockout_total", 0), 15.0)
        self.assertAlmostEqual(summary.get("penalty_backorder_total", 0), 10.0)
        self.assertAlmostEqual(summary.get("penalty_total", 0), 25.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
