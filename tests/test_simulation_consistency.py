import unittest
import math
import random

from main import SimulationInput, SupplyChainSimulator, StoreNode, WarehouseNode, FactoryNode


def build_sample_input():
    return {
        "planning_horizon": 20,
        "products": [
            {
                "name": "完成品A",
                "sales_price": 1500,
                "assembly_bom": [
                    {"item_name": "材料X", "quantity_per": 2},
                    {"item_name": "材料Y", "quantity_per": 5},
                ],
            }
        ],
        "nodes": [
            {"name": "店舗1", "node_type": "store", "initial_stock": {"完成品A": 30}, "service_level": 0.95, "moq": {"完成品A": 10}, "order_multiple": {"完成品A": 5}, "backorder_enabled": True},
            {"name": "中央倉庫", "node_type": "warehouse", "initial_stock": {"完成品A": 100}, "service_level": 0.90, "moq": {"完成品A": 30}, "order_multiple": {"完成品A": 10}, "backorder_enabled": True},
            {"name": "組立工場", "node_type": "factory", "producible_products": ["完成品A"], "initial_stock": {"完成品A": 50, "材料X": 500, "材料Y": 800}, "lead_time": 14, "production_capacity": 50, "reorder_point": {"材料X": 200, "材料Y": 400}, "order_up_to_level": {"材料X": 500, "材料Y": 800}, "moq": {"材料X": 50, "材料Y": 100}, "order_multiple": {"材料X": 25, "材料Y": 50}, "backorder_enabled": True},
            {"name": "サプライヤーX", "node_type": "material", "initial_stock": {"材料X": 10000}, "material_cost": {"材料X": 100}, "backorder_enabled": True},
            {"name": "サプライヤーY", "node_type": "material", "initial_stock": {"材料Y": 10000}, "material_cost": {"材料Y": 20}, "backorder_enabled": True},
        ],
        "network": [
            {"from_node": "中央倉庫", "to_node": "店舗1", "transportation_cost_fixed": 200, "transportation_cost_variable": 3, "lead_time": 3, "moq": {"完成品A": 20}, "order_multiple": {"完成品A": 10}},
            {"from_node": "組立工場", "to_node": "中央倉庫", "transportation_cost_fixed": 500, "transportation_cost_variable": 2, "lead_time": 7},
            {"from_node": "サプライヤーX", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 30},
            {"from_node": "サプライヤーY", "to_node": "組立工場", "transportation_cost_fixed": 1000, "transportation_cost_variable": 1, "lead_time": 20},
        ],
        "customer_demand": [
            {"store_name": "店舗1", "product_name": "完成品A", "demand_mean": 15, "demand_std_dev": 2},
        ],
    }


class TestSimulationConsistency(unittest.TestCase):
    def setUp(self):
        random.seed(0)
        self.input = SimulationInput(**build_sample_input())
        self.sim = SupplyChainSimulator(self.input)
        self.results, self.pl = self.sim.run()

    def test_psi_identity_and_stock_flow(self):
        # For each day/node/item ensure: demand == sales + shortage
        # and end_stock == start_stock + incoming + produced - sales - consumption (within tolerance)
        for day in self.results:
            for node, items in day["nodes"].items():
                for item, metrics in items.items():
                    demand = metrics.get("demand", 0)
                    sales = metrics.get("sales", 0)
                    shortage = metrics.get("shortage", 0)
                    self.assertAlmostEqual(demand, sales + shortage, places=6, msg=f"Day {day['day']} {node}-{item}: PSI identity failed")

                    start_stock = metrics.get("start_stock", 0)
                    end_stock = metrics.get("end_stock", 0)
                    incoming = metrics.get("incoming", 0)
                    produced = metrics.get("produced", 0)
                    consumption = metrics.get("consumption", 0)

                    lhs = start_stock + incoming + produced - sales - consumption
                    self.assertTrue(math.isclose(lhs, end_stock, rel_tol=1e-7, abs_tol=1e-7),
                                    msg=f"Day {day['day']} {node}-{item}: stock flow mismatch: lhs={lhs}, end={end_stock}")

    def test_cumulative_order_balance(self):
        # Ordered == Received + InTransit (end)
        in_transit_at_end = {}
        for arrival_day, orders in self.sim.in_transit_orders.items():
            for item, qty, dest, _src in orders:
                key = (dest, item)
                in_transit_at_end[key] = in_transit_at_end.get(key, 0) + qty

        all_keys = set(self.sim.cumulative_ordered.keys()) | set(self.sim.cumulative_received.keys()) | set(in_transit_at_end.keys())
        for key in all_keys:
            ordered = self.sim.cumulative_ordered.get(key, 0)
            received = self.sim.cumulative_received.get(key, 0)
            in_transit = in_transit_at_end.get(key, 0)
            self.assertTrue(math.isclose(ordered, received + in_transit, rel_tol=1e-9, abs_tol=1e-9),
                            msg=f"Cumulative balance failed for {key}: ordered={ordered}, received={received}, in_transit={in_transit}")

    def test_moq_and_multiples_applied(self):
        # Verify each placed order respects node/link MOQ and integer multiples when integers are specified
        nodes_map = {n.name: n for n in self.input.nodes}
        network_map = {(l.from_node, l.to_node): l for l in self.input.network}

        for day, orders in self.sim.order_history.items():
            for item, qty, supplier, dest in orders:
                dest_node = nodes_map.get(dest)
                link = network_map.get((supplier, dest))
                if dest_node is None or link is None:
                    # Skip customer-facing or legacy entries
                    continue

                # MOQ
                node_moq = getattr(dest_node, 'moq', {}).get(item, 0)
                link_moq = getattr(link, 'moq', {}).get(item, 0)
                eff_moq = max(node_moq or 0, link_moq or 0)
                if eff_moq > 0:
                    self.assertGreaterEqual(qty, eff_moq, msg=f"Day {day} {supplier}->{dest} {item}: qty {qty} < MOQ {eff_moq}")

                # Order multiples (only enforce integer multiples explicitly)
                for mult in (getattr(dest_node, 'order_multiple', {}).get(item, 0), getattr(link, 'order_multiple', {}).get(item, 0)):
                    if mult and abs(mult - round(mult)) < 1e-9 and round(mult) > 0:
                        m = int(round(mult))
                        self.assertEqual(qty % m, 0, msg=f"Day {day} {supplier}->{dest} {item}: qty {qty} not multiple of {m}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

