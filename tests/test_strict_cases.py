import unittest
import random

from main import SimulationInput, SupplyChainSimulator


class TestStrictCases(unittest.TestCase):
    def test_warehouse_orders_include_scheduled_outgoing(self):
        # Deterministic setup: two stores, zero stddev, SL=0, stores/warehouse start at 0 stock.
        # Expect: wh order on day0 = order_up_to_wh + sum(store orders scheduled outgoing)
        random.seed(0)
        sim_input = {
            "planning_horizon": 2,
            "products": [{"name": "完成品A", "sales_price": 1000, "assembly_bom": []}],
            "nodes": [
                {
                    "name": "店舗1",
                    "node_type": "store",
                    "initial_stock": {"完成品A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
                {
                    "name": "店舗2",
                    "node_type": "store",
                    "initial_stock": {"完成品A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
                {
                    "name": "中央倉庫",
                    "node_type": "warehouse",
                    "initial_stock": {"完成品A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
                {
                    "name": "組立工場",
                    "node_type": "factory",
                    "producible_products": ["完成品A"],
                    "initial_stock": {"完成品A": 0},
                    "lead_time": 1,
                    "production_capacity": 100000,
                    "backorder_enabled": True,
                },
            ],
            "network": [
                {"from_node": "中央倉庫", "to_node": "店舗1", "lead_time": 3},
                {"from_node": "中央倉庫", "to_node": "店舗2", "lead_time": 3},
                {"from_node": "組立工場", "to_node": "中央倉庫", "lead_time": 1},
            ],
            "customer_demand": [
                {
                    "store_name": "店舗1",
                    "product_name": "完成品A",
                    "demand_mean": 10,
                    "demand_std_dev": 0,
                },
                {
                    "store_name": "店舗2",
                    "product_name": "完成品A",
                    "demand_mean": 5,
                    "demand_std_dev": 0,
                },
            ],
        }

        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()

        # Day 0 orders from stores to warehouse
        day0_orders = sim.order_history.get(0, [])
        s_to_w = sum(
            q
            for item, q, src, dest in day0_orders
            if (item, src, dest) == ("完成品A", "中央倉庫", "店舗1")
        ) + sum(
            q
            for item, q, src, dest in day0_orders
            if (item, src, dest) == ("完成品A", "中央倉庫", "店舗2")
        )

        # Expected store orders: S1 = 10*(LT+1) + backlog(=10) = 50; S2 = 5*(LT+1) + 5 = 25
        # Because SL=0, z=0, LT=3, inv_pos includes -BO after demand
        self.assertEqual(s_to_w, 50 + 25)

        # Warehouse demand profile: mean=15, std=0, LT(工場->倉庫) = 1
        # order_up_to_wh = 15*(1+1) = 30; inv_pos = - scheduled_outgoing (75)
        # qty_wh = 30 - (-75) = 105
        w_to_f = sum(
            q
            for item, q, src, dest in day0_orders
            if (item, src, dest) == ("完成品A", "中央倉庫", "組立工場")
        )
        self.assertEqual(w_to_f, 105)

    def test_lcm_order_multiple_rounding(self):
        # If node multiple=4 and link multiple=6, effective multiple=LCM(4,6)=12
        # Base qty=50 should round up to 60
        random.seed(0)
        sim_input = {
            "planning_horizon": 1,
            "products": [{"name": "完成品A", "sales_price": 1000, "assembly_bom": []}],
            "nodes": [
                {
                    "name": "店舗1",
                    "node_type": "store",
                    "initial_stock": {"完成品A": 0},
                    "service_level": 0.0,
                    "order_multiple": {"完成品A": 4},
                },
                {
                    "name": "中央倉庫",
                    "node_type": "warehouse",
                    "initial_stock": {"完成品A": 0},
                    "service_level": 0.0,
                },
            ],
            "network": [
                {
                    "from_node": "中央倉庫",
                    "to_node": "店舗1",
                    "lead_time": 3,
                    "order_multiple": {"完成品A": 6},
                },
            ],
            "customer_demand": [
                {
                    "store_name": "店舗1",
                    "product_name": "完成品A",
                    "demand_mean": 10,
                    "demand_std_dev": 0,
                }
            ],
        }
        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()
        day0_orders = sim.order_history.get(0, [])
        store_order = sum(
            q
            for item, q, src, dest in day0_orders
            if (item, src, dest) == ("完成品A", "中央倉庫", "店舗1")
        )
        # Base (without multiples): 10*(3+1)+10 = 50
        self.assertEqual(store_order, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
