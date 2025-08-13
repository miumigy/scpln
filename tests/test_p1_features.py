import unittest
import random

from main import SimulationInput, SupplyChainSimulator


class TestLostSalesAndReviewPeriod(unittest.TestCase):
    def test_lost_sales_no_backorder_accumulation(self):
        random.seed(0)
        sim_input = {
            "planning_horizon": 1,
            "products": [{"name": "A", "sales_price": 0, "assembly_bom": []}],
            "nodes": [
                {"name": "S", "node_type": "store", "initial_stock": {"A": 0}, "service_level": 0.0, "lost_sales": True},
                {"name": "W", "node_type": "warehouse", "initial_stock": {"A": 0}, "service_level": 0.0},
            ],
            "network": [
                {"from_node": "W", "to_node": "S", "lead_time": 3}
            ],
            "customer_demand": [
                {"store_name": "S", "product_name": "A", "demand_mean": 10, "demand_std_dev": 0}
            ],
        }
        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()
        # lost_sales=True のため、顧客バックオーダーは積まれない
        self.assertEqual(sim.customer_backorders["S"].get("A", 0), 0)
        # day0 の発注は 10*(L+1) = 40（BO控除なし）
        day0_orders = sim.order_history.get(0, [])
        qty = sum(q for it, q, src, dest in day0_orders if (it, src, dest) == ("A", "W", "S"))
        self.assertEqual(qty, 40)

    def test_review_period_expands_order_upto(self):
        random.seed(0)
        sim_input = {
            "planning_horizon": 1,
            "products": [{"name": "A", "sales_price": 0, "assembly_bom": []}],
            "nodes": [
                {"name": "S", "node_type": "store", "initial_stock": {"A": 0}, "service_level": 0.0, "review_period_days": 2},
                {"name": "W", "node_type": "warehouse", "initial_stock": {"A": 0}, "service_level": 0.0},
            ],
            "network": [
                {"from_node": "W", "to_node": "S", "lead_time": 3}
            ],
            "customer_demand": [
                {"store_name": "S", "product_name": "A", "demand_mean": 10, "demand_std_dev": 0}
            ],
        }
        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()
        # R=2 により μ*(L+R+1)=10*(3+2+1)=60。
        # さらに day0 で顧客BO=10 を控除するため、発注量は 60 - (-10) = 70
        day0_orders = sim.order_history.get(0, [])
        qty = sum(q for it, q, src, dest in day0_orders if (it, src, dest) == ("A", "W", "S"))
        self.assertEqual(qty, 70)


if __name__ == "__main__":
    unittest.main(verbosity=2)
