import unittest
import pytest
from main import SupplyChainSimulator, SimulationInput

class TestDailySnapshotIdentities(unittest.TestCase):

    def test_daily_snapshot_identities(self):
        # ダミーの最小入力 payload
        sim_input_payload = {
            "planning_horizon": 5,
            "products": [
                {"name": "itemA", "sales_price": 100.0, "assembly_bom": []}
            ],
            "nodes": [
                {
                    "name": "mat1",
                    "node_type": "material",
                    "initial_stock": {"itemA": 1000},
                    "material_cost": {"itemA": 20.0},
                },
                {
                    "name": "fac1",
                    "node_type": "factory",
                    "initial_stock": {"itemA": 0},
                    "producible_products": ["itemA"],
                    "production_capacity": 50,
                    "production_cost_fixed": 500.0,
                    "production_cost_variable": 10.0,
                },
                {
                    "name": "wh1",
                    "node_type": "warehouse",
                    "initial_stock": {"itemA": 0},
                    "storage_capacity": 500,
                    "storage_cost_fixed": 100.0,
                    "storage_cost_variable": {"itemA": 1.0},
                },
                {
                    "name": "st1",
                    "node_type": "store",
                    "initial_stock": {"itemA": 0},
                },
            ],
            "network": [
                {
                    "from_node": "mat1",
                    "to_node": "fac1",
                    "transportation_cost_fixed": 50.0,
                    "transportation_cost_variable": 2.0,
                    "lead_time": 0,
                },
                {
                    "from_node": "fac1",
                    "to_node": "wh1",
                    "transportation_cost_fixed": 30.0,
                    "transportation_cost_variable": 1.0,
                    "lead_time": 0,
                },
                {
                    "from_node": "wh1",
                    "to_node": "st1",
                    "transportation_cost_fixed": 20.0,
                    "transportation_cost_variable": 1.0,
                    "lead_time": 0,
                },
            ],
            "customer_demand": [
                {
                    "store_name": "st1",
                    "product_name": "itemA",
                    "demand_mean": 30,
                    "demand_std_dev": 0.0,
                }
            ],
        }

        # シミュレーションの実行
        sim_input = SimulationInput(**sim_input_payload)
        simulator = SupplyChainSimulator(sim_input)
        daily_results, _ = simulator.run()

        # daily_results を走査し、各 node/item の日次で恒等式を検査
        for day_data in daily_results:
            day = day_data["day"]
            for node_name, node_data in day_data["nodes"].items():
                for item_name, item_data in node_data.items():
                    # 各種メトリクスを取得 (存在しない場合は0をデフォルト値とする)
                    start_stock = item_data.get("start_stock", 0)
                    end_stock = item_data.get("end_stock", 0)
                    incoming = item_data.get("incoming", 0)
                    produced = item_data.get("produced", 0)
                    sales = item_data.get("sales", 0)
                    consumption = item_data.get("consumption", 0)
                    shortage = item_data.get("shortage", 0)
                    demand = item_data.get("demand", 0)
                    backorder_balance = item_data.get("backorder_balance", 0)

                    print(f"DEBUG: Day {day}, Node {node_name}, Item {item_name}")
                    print(f"  Demand: {demand}, Sales: {sales}, Shortage: {shortage}")

                    # demand == sales + shortage の検査
                    with self.subTest(msg=f"Day {day}, Node {node_name}, Item {item_name}: Demand Identity"):
                        self.assertAlmostEqual(demand, sales + shortage, msg=f"Demand ({demand}) != Sales ({sales}) + Shortage ({shortage})")

                    # 在庫恒等式の検査
                    # end_stock = start_stock + incoming + produced - sales - consumption
                    # 浮動小数点数の比較のため assertAlmostEqual を使用
                    expected_end_stock = start_stock + incoming + produced - sales - consumption
                    with self.subTest(msg=f"Day {day}, Node {node_name}, Item {item_name}: Stock Identity"):
                        self.assertAlmostEqual(end_stock, expected_end_stock, places=5, msg=f"End Stock ({end_stock}) != Expected End Stock ({expected_end_stock})")

                    # 欠品/BOは負にならないことを検査
                    with self.subTest(msg=f"Day {day}, Node {node_name}, Item {item_name}: Non-negative Shortage"):
                        self.assertGreaterEqual(shortage, 0, msg=f"Shortage ({shortage}) is negative")
                    
                    with self.subTest(msg=f"Day {day}, Node {node_name}, Item {item_name}: Non-negative Backorder"):
                        self.assertGreaterEqual(backorder_balance, 0, msg=f"Backorder Balance ({backorder_balance}) is negative")

if __name__ == '__main__':
    unittest.main()
