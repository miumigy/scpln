import unittest
import random

from main import SimulationInput, SupplyChainSimulator


class TestFactoryEnhancements(unittest.TestCase):
    def test_factory_production_accounts_for_scheduled_outgoing(self):
        # Setup similar to strict case but assert factory production uses scheduled outgoing
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
                    "service_level": 0.0,
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
        results, _ = sim.run()

        # On day 0, warehouse orders 105 to factory; factory lead_time=1; FG SL=0
        # order_up_to_factory = 15*(1+1)=30; inv_pos = 0 - 105 => production_needed = 135
        produced_day1 = 0
        # Day index 1 corresponds to Day 2 in results
        for node, items in results[1]["nodes"].items():
            if node == "組立工場":
                produced_day1 = items.get("完成品A", {}).get("produced", 0)
        self.assertEqual(
            produced_day1,
            135,
            msg=f"Factory production on day1 should account for scheduled outgoing; got {produced_day1}",
        )

    def test_factory_component_orders_apply_link_constraints(self):
        # Factory should apply link-level MOQ and multiples (LCM) for component orders
        random.seed(0)
        sim_input = {
            "planning_horizon": 1,
            "products": [
                {
                    "name": "完成品A",
                    "sales_price": 1000,
                    "assembly_bom": [{"item_name": "材料X", "quantity_per": 1}],
                }
            ],
            "nodes": [
                {
                    "name": "組立工場",
                    "node_type": "factory",
                    "producible_products": ["完成品A"],
                    "initial_stock": {"材料X": 0},
                    "lead_time": 1,
                    "production_capacity": 100000,
                    "reorder_point": {"材料X": 0},
                    "order_up_to_level": {"材料X": 50},
                    "order_multiple": {"材料X": 4},
                    "moq": {"材料X": 40},
                    "backorder_enabled": True,
                },
                {
                    "name": "サプライヤーX",
                    "node_type": "material",
                    "initial_stock": {"材料X": 10000},
                    "material_cost": {"材料X": 1},
                    "backorder_enabled": True,
                },
            ],
            "network": [
                {
                    "from_node": "サプライヤーX",
                    "to_node": "組立工場",
                    "lead_time": 1,
                    "order_multiple": {"材料X": 6},
                    "moq": {"材料X": 20},
                }
            ],
            "customer_demand": [],
        }

        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()

        day0_orders = sim.order_history.get(0, [])
        ordered = sum(
            q
            for item, q, src, dest in day0_orders
            if (item, src, dest) == ("材料X", "サプライヤーX", "組立工場")
        )
        # Base qty = 50; node mult=4, link mult=6 -> LCM=12; expect 60 (>= max MOQ 40)
        self.assertEqual(
            ordered, 60, msg=f"Expected LCM-rounded order 60, got {ordered}"
        )

    def test_factory_zero_lead_time_produces_with_offset(self):
        # Zero production lead time should still yield completed production in subsequent days
        random.seed(0)
        sim_input = {
            "planning_horizon": 10,
            "products": [{"name": "製品A", "sales_price": 500}],
            "nodes": [
                {
                    "name": "店舗",
                    "node_type": "store",
                    "initial_stock": {"製品A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
                {
                    "name": "倉庫",
                    "node_type": "warehouse",
                    "initial_stock": {"製品A": 20},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
                {
                    "name": "工場",
                    "node_type": "factory",
                    "producible_products": ["製品A"],
                    "initial_stock": {"製品A": 0},
                    "lead_time": 0,
                    "production_capacity": 1000,
                    "service_level": 0.95,
                    "backorder_enabled": True,
                },
            ],
            "network": [
                {"from_node": "工場", "to_node": "倉庫", "lead_time": 2},
                {"from_node": "倉庫", "to_node": "店舗", "lead_time": 1},
            ],
            "customer_demand": [
                {
                    "store_name": "店舗",
                    "product_name": "製品A",
                    "demand_mean": 10,
                    "demand_std_dev": 0,
                }
            ],
        }

        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        results, _ = sim.run()

        produced = [
            nodes.get("製品A", {}).get("produced", 0)
            for day in results
            for name, nodes in day["nodes"].items()
            if name == "工場"
        ]
        self.assertTrue(
            any(p > 0 for p in produced),
            msg=f"Expected factory production with zero lead time, got {produced}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
