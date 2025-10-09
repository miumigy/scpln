import unittest
import math
import random

from main import SimulationInput, SupplyChainSimulator


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
            },
            {
                "name": "完成品B",
                "sales_price": 1800,
                "assembly_bom": [
                    {"item_name": "材料Y", "quantity_per": 3},
                    {"item_name": "材料Z", "quantity_per": 4},
                ],
            },
        ],
        "nodes": [
            {
                "name": "店舗1",
                "node_type": "store",
                "initial_stock": {"完成品A": 30, "完成品B": 10},
                "service_level": 0.95,
                "moq": {"完成品A": 10, "完成品B": 10},
                "order_multiple": {"完成品A": 5, "完成品B": 5},
                "backorder_enabled": True,
            },
            {
                "name": "店舗2",
                "node_type": "store",
                "initial_stock": {"完成品A": 20, "完成品B": 5},
                "service_level": 0.95,
                "moq": {"完成品A": 10, "完成品B": 10},
                "order_multiple": {"完成品A": 5, "完成品B": 5},
                "backorder_enabled": True,
            },
            {
                "name": "中央倉庫",
                "node_type": "warehouse",
                "initial_stock": {"完成品A": 100, "完成品B": 50},
                "service_level": 0.90,
                "moq": {"完成品A": 30, "完成品B": 30},
                "order_multiple": {"完成品A": 10, "完成品B": 10},
                "backorder_enabled": True,
            },
            {
                "name": "組立工場",
                "node_type": "factory",
                "producible_products": ["完成品A", "完成品B"],
                "initial_stock": {
                    "完成品A": 50,
                    "完成品B": 20,
                    "材料X": 500,
                    "材料Y": 800,
                    "材料Z": 600,
                },
                "lead_time": 14,
                "production_capacity": 50,
                "reorder_point": {"材料X": 200, "材料Y": 400, "材料Z": 300},
                "order_up_to_level": {"材料X": 500, "材料Y": 800, "材料Z": 600},
                "moq": {"材料X": 50, "材料Y": 100, "材料Z": 100},
                "order_multiple": {"材料X": 25, "材料Y": 50, "材料Z": 50},
                "backorder_enabled": True,
            },
            {
                "name": "サプライヤーX",
                "node_type": "material",
                "initial_stock": {"材料X": 10000},
                "material_cost": {"材料X": 100},
                "backorder_enabled": True,
            },
            {
                "name": "サプライヤーY",
                "node_type": "material",
                "initial_stock": {"材料Y": 10000},
                "material_cost": {"材料Y": 20},
                "backorder_enabled": True,
            },
            {
                "name": "サプライヤーZ",
                "node_type": "material",
                "initial_stock": {"材料Z": 10000},
                "material_cost": {"材料Z": 30},
                "backorder_enabled": True,
            },
        ],
        "network": [
            {
                "from_node": "中央倉庫",
                "to_node": "店舗1",
                "transportation_cost_fixed": 200,
                "transportation_cost_variable": 3,
                "lead_time": 3,
                "moq": {"完成品A": 20, "完成品B": 20},
                "order_multiple": {"完成品A": 10, "完成品B": 10},
            },
            {
                "from_node": "中央倉庫",
                "to_node": "店舗2",
                "transportation_cost_fixed": 200,
                "transportation_cost_variable": 3,
                "lead_time": 3,
                "moq": {"完成品A": 20, "完成品B": 20},
                "order_multiple": {"完成品A": 10, "完成品B": 10},
            },
            {
                "from_node": "組立工場",
                "to_node": "中央倉庫",
                "transportation_cost_fixed": 500,
                "transportation_cost_variable": 2,
                "lead_time": 7,
            },
            {
                "from_node": "サプライヤーX",
                "to_node": "組立工場",
                "transportation_cost_fixed": 1000,
                "transportation_cost_variable": 1,
                "lead_time": 30,
            },
            {
                "from_node": "サプライヤーY",
                "to_node": "組立工場",
                "transportation_cost_fixed": 1000,
                "transportation_cost_variable": 1,
                "lead_time": 20,
            },
            {
                "from_node": "サプライヤーZ",
                "to_node": "組立工場",
                "transportation_cost_fixed": 1000,
                "transportation_cost_variable": 1,
                "lead_time": 25,
            },
        ],
        "customer_demand": [
            {
                "store_name": "店舗1",
                "product_name": "完成品A",
                "demand_mean": 15,
                "demand_std_dev": 2,
            },
            {
                "store_name": "店舗1",
                "product_name": "完成品B",
                "demand_mean": 8,
                "demand_std_dev": 1.5,
            },
            {
                "store_name": "店舗2",
                "product_name": "完成品B",
                "demand_mean": 6,
                "demand_std_dev": 1.0,
            },
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
                    self.assertAlmostEqual(
                        demand,
                        sales + shortage,
                        places=6,
                        msg=f"Day {day['day']} {node}-{item}: PSI identity failed",
                    )

                    start_stock = metrics.get("start_stock", 0)
                    end_stock = metrics.get("end_stock", 0)
                    incoming = metrics.get("incoming", 0)
                    produced = metrics.get("produced", 0)
                    consumption = metrics.get("consumption", 0)

                    lhs = start_stock + incoming + produced - sales - consumption
                    self.assertTrue(
                        math.isclose(lhs, end_stock, rel_tol=1e-7, abs_tol=1e-7),
                        msg=f"Day {day['day']} {node}-{item}: stock flow mismatch: lhs={lhs}, end={end_stock}",
                    )

    def test_cumulative_order_balance(self):
        # For each (dest,item): total ordered == total incoming (shipments) + pending shipments scheduled after horizon
        # Note: production receipts are not part of 'incoming' for shipments; we only count transport arrivals.
        total_incoming = {}
        for day in self.results:
            for node, items in day["nodes"].items():
                for item, metrics in items.items():
                    inc = metrics.get("incoming", 0) or 0
                    if inc:
                        key = (node, item)
                        total_incoming[key] = total_incoming.get(key, 0) + inc

        pending_future = {}
        # pending_shipments structure: day -> list of tuples (item, qty, supplier, dest, is_backorder?)
        for d, records in self.sim.pending_shipments.items():
            # all remaining entries are future relative to the last simulated day
            for rec in records:
                if len(rec) == 4:
                    it, q, _src, dest = rec
                else:
                    it, q, _src, dest, _ = rec
                key = (dest, it)
                pending_future[key] = pending_future.get(key, 0) + q

        # Sum ordered by destination
        ordered_by_dest = {}
        for day, orders in self.sim.order_history.items():
            for it, q, _src, dest in orders:
                key = (dest, it)
                ordered_by_dest[key] = ordered_by_dest.get(key, 0) + q

        keys = (
            set(ordered_by_dest.keys())
            | set(total_incoming.keys())
            | set(pending_future.keys())
        )
        for key in keys:
            ordered = ordered_by_dest.get(key, 0)
            incoming = total_incoming.get(key, 0)
            future = pending_future.get(key, 0)
            self.assertTrue(
                math.isclose(ordered, incoming + future, rel_tol=1e-9, abs_tol=1e-9),
                msg=f"Cumulative balance failed for {key}: ordered={ordered}, incoming={incoming}, pending={future}",
            )

    def test_moq_and_multiples_applied(self):
        # Verify each placed order respects node/link MOQ and integer multiples when integers are specified
        nodes_map = {n.name: n for n in self.input.nodes}
        network_map = {(link.from_node, link.to_node): link for link in self.input.network}

        for day, orders in self.sim.order_history.items():
            for item, qty, supplier, dest in orders:
                dest_node = nodes_map.get(dest)
                link = network_map.get((supplier, dest))
                if dest_node is None or link is None:
                    # Skip customer-facing or legacy entries
                    continue

                # MOQ
                node_moq = getattr(dest_node, "moq", {}).get(item, 0)
                link_moq = getattr(link, "moq", {}).get(item, 0)
                eff_moq = max(node_moq or 0, link_moq or 0)
                if eff_moq > 0:
                    self.assertGreaterEqual(
                        qty,
                        eff_moq,
                        msg=f"Day {day} {supplier}->{dest} {item}: qty {qty} < MOQ {eff_moq}",
                    )

                # Order multiples (only enforce integer multiples explicitly)
                for mult in (
                    getattr(dest_node, "order_multiple", {}).get(item, 0),
                    getattr(link, "order_multiple", {}).get(item, 0),
                ):
                    if mult and abs(mult - round(mult)) < 1e-9 and round(mult) > 0:
                        m = int(round(mult))
                        self.assertEqual(
                            qty % m,
                            0,
                            msg=f"Day {day} {supplier}->{dest} {item}: qty {qty} not multiple of {m}",
                        )

    def test_backorder_pipeline_prevents_order_balloon(self):
        # Deterministic scenario: zero stddev, SL=0 to remove z-term, LT=3
        # Expect day0 places a large order equal to mean*(LT+1),
        # subsequent days top-up by mean (not repeat the large order) -> non-increasing sequence
        sim_input = build_sample_input()
        sim_input["planning_horizon"] = 6
        # Override params for determinism and no rounding constraints
        for n in sim_input["nodes"]:
            if n["node_type"] in ("store", "warehouse"):
                n["service_level"] = 0.0
                n.pop("moq", None)
                n.pop("order_multiple", None)
            if n["node_type"] == "store":
                n["initial_stock"] = {"完成品A": 0}
            if n["node_type"] == "warehouse":
                n["initial_stock"] = {"完成品A": 0}
        for link in sim_input["network"]:
            if link["to_node"] == "店舗1":
                link["lead_time"] = 3
                link.pop("moq", None)
                link.pop("order_multiple", None)
        sim_input["customer_demand"][0]["demand_mean"] = 10
        sim_input["customer_demand"][0]["demand_std_dev"] = 0

        sim = SupplyChainSimulator(SimulationInput(**sim_input))
        sim.run()

        # Collect store orders by day
        store_orders_by_day = []
        for day in sorted(sim.order_history.keys()):
            day_qty = 0
            for item, qty, supplier, dest in sim.order_history[day]:
                if dest == "店舗1" and supplier == "中央倉庫" and item == "完成品A":
                    day_qty += qty
            if day_qty > 0:
                store_orders_by_day.append(day_qty)

        # Expectations: first order is between mean*(LT+1) and mean*(LT+1)+backlog (backlog ~ mean on day0),
        # subsequent orders <= mean
        self.assertGreaterEqual(
            len(store_orders_by_day), 1, msg="No store orders recorded"
        )
        first = store_orders_by_day[0]
        mean = 10
        lt = 3
        expected_lower = mean * (lt + 1)
        expected_upper = expected_lower + mean
        self.assertGreaterEqual(
            first,
            expected_lower - 1e-9,
            msg=f"First order too small: {first} < {expected_lower}",
        )
        self.assertLessEqual(
            first,
            expected_upper + 1e-9,
            msg=f"First order too large: {first} > {expected_upper}",
        )

        for q in store_orders_by_day[1:5]:
            self.assertLessEqual(
                q,
                mean + 1e-9,
                msg=f"Top-up order too large: {q} > {mean}; orders={store_orders_by_day}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
