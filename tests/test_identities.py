import unittest
import pytest
from main import SupplyChainSimulator, SimulationInput

class TestDailySnapshotIdentities(unittest.TestCase):

    def test_daily_snapshot_identities(self):
        pytest.skip("TODO: fill minimal scenario")

        # ダミーの最小入力 payload
        sim_input_payload = {
            # TODO: ユーザーがここに最小限のシミュレーション入力データを埋める
            # 例:
            # "planning_horizon": 1,
            # "products": [{"name": "ProductA", "sales_price": 100, "assembly_bom": []}],
            # "nodes": [
            #     {"name": "Store1", "node_type": "store", "initial_stock": {"ProductA": 10}},
            #     {"name": "Warehouse1", "node_type": "warehouse", "initial_stock": {"ProductA": 50}},
            # ],
            # "network": [
            #     {"from_node": "Warehouse1", "to_node": "Store1", "lead_time": 1},
            # ],
            # "customer_demand": [
            #     {"store_name": "Store1", "product_name": "ProductA", "demand_mean": 5, "demand_std_dev": 0},
            # ],
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
