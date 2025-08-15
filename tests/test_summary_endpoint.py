import unittest
from fastapi.testclient import TestClient
from app.api import app


class TestSummaryEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_summary_flow(self):
        # Before any run, /summary should 404
        r = self.client.get("/summary")
        self.assertEqual(r.status_code, 404)

        payload = {
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
                },
                {
                    "name": "W",
                    "node_type": "warehouse",
                    "initial_stock": {"A": 0},
                    "service_level": 0.0,
                    "backorder_enabled": True,
                },
            ],
            "network": [{"from_node": "W", "to_node": "S", "lead_time": 1}],
            "customer_demand": [
                {
                    "store_name": "S",
                    "product_name": "A",
                    "demand_mean": 1,
                    "demand_std_dev": 0,
                }
            ],
        }
        r = self.client.post("/simulation", json=payload)
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get("/summary")
        self.assertEqual(r2.status_code, 200)
        data = r2.json()
        self.assertIn("penalty_total", data)
        self.assertIn("fill_rate", data)

    def test_validation_unknown_link(self):
        payload = {
            "planning_horizon": 1,
            "products": [],
            "nodes": [
                {
                    "name": "S",
                    "node_type": "store",
                    "initial_stock": {},
                    "service_level": 0.0,
                }
            ],
            "network": [{"from_node": "X", "to_node": "S", "lead_time": 1}],
            "customer_demand": [],
        }
        r = self.client.post("/simulation", json=payload)
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
