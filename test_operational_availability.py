import copy
import unittest
from unittest.mock import patch
import app
from gerar_dashboard_ads_ml import render_dashboard


class OperationalAvailabilityTests(unittest.TestCase):
    def payload(self):
        identity = dict(client_id="demo", advertiser_id="7", date_from="2026-09-01", date_to="2026-09-02")
        return dict(ok=True, operational_partial=True, client_id="demo", period_cache_hit=True,
                    latest={**identity, "sales": {"complete": False}},
                    ads={**identity, "items": [{"item_id": "MLB123", "cost": 10, "clicks": 20, "prints": 100, "total_amount": 40}]},
                    sales={**identity, "items": {"MLB123": {"revenue_total": 20, "units_total": 1, "orders_count": 1}}},
                    daily_ads=[], daily_sales=[])

    def test_partial_cache_renders_without_billing_or_repair(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value=self.payload()) as fetch:
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertIsNotNone(data)
        self.assertFalse(data["meta"]["onlineMode"]["complete"])
        self.assertIn("DADOS PARCIAIS", render_dashboard(data))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args[0], "/internal/dash-ads/operational-cache")
        self.assertEqual(fetch.call_args_list[1].args[0], "/internal/dash-ads/returns-summary")

    def test_partial_cache_still_reads_independent_returns(self):
        returns = {
            "ok": True, "complete": True,
            "date_from": "2026-09-01", "date_to": "2026-09-02",
            "amount": 12.50, "returns_count": 1,
            "returned_orders_count": 1, "orders_total": 10,
            "orders_total_available": True,
        }
        with patch.object(app, "_fetch_dash_ads_json", side_effect=[self.payload(), returns]) as fetch:
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertTrue(data["kpis"]["returnsAvailable"])
        self.assertTrue(data["kpis"]["returnsOrdersAvailable"])
        self.assertEqual(data["kpis"]["returnsAmount"], 12.50)
        self.assertEqual(fetch.call_args_list[1].args[0], "/internal/dash-ads/returns-summary")

    def test_confirmed_returned_orders_count_remains_visible_without_order_universe(self):
        returns = {
            "ok": True, "complete": True,
            "date_from": "2026-09-01", "date_to": "2026-09-02",
            "amount": 12.50, "returns_count": 1,
            "returned_orders_count": 2, "orders_total_available": False,
        }
        with patch.object(app, "_fetch_dash_ads_json", side_effect=[self.payload(), returns]):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertTrue(data["kpis"]["returnsAvailable"])
        self.assertFalse(data["kpis"]["returnsOrdersAvailable"])
        self.assertEqual(data["kpis"]["returnsOrdersCount"], 2)
        html = render_dashboard(data)
        self.assertIn("taxa N/D", html)

    def test_rejects_other_account_period_and_advertiser(self):
        for field, value in (("client_id", "other"), ("date_from", "2026-08-01"), ("advertiser_id", "8")):
            payload = copy.deepcopy(self.payload())
            payload["ads"][field] = value
            with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
                data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
            self.assertIsNone(data)
            self.assertTrue(error)

    def test_sales_only_still_opens(self):
        payload = self.payload()
        payload["ads"]["items"] = []
        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, _ = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNotNone(data)

    def test_empty_cache_not_presented_as_zero(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value={"ok": False}):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNone(data)
        self.assertIn("não há dados", error)

    def test_intelligence_remains_strict(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value=self.payload()):
            data, error = app._sales_intelligence_fetch_latest("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNone(data)
        self.assertTrue(error)

def load_tests(loader, tests, pattern):
    from test_performance_7d import PerformanceTests
    tests.addTests(loader.loadTestsFromTestCase(PerformanceTests))
    return tests
