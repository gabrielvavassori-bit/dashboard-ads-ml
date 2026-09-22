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
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], "/internal/dash-ads/operational-cache")

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
        with patch.object(app, "_fetch_dash_ads_json", side_effect=[{"ok": False}, {"status": {}}]):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNone(data)
        self.assertIn("não há dados", error)

    def test_initial_collection_is_presented_as_pending_without_triggering_refresh(self):
        with patch.object(
            app,
            "_fetch_dash_ads_json",
            side_effect=[{"ok": False}, {"ok": False, "status": {"status": "running"}}],
        ) as fetch:
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNone(data)
        self.assertTrue(error.startswith(app.ONLINE_CACHE_PENDING_PREFIX))
        self.assertIn("coleta inicial", error)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args[0], "/internal/dash-ads/operational-cache")
        self.assertEqual(fetch.call_args_list[1].args[0], "/internal/dash-ads/online-cache-status")

    def test_intelligence_remains_strict(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value=self.payload()):
            data, error = app._sales_intelligence_fetch_latest("demo", "7", "2026-09-01", "2026-09-02")
        self.assertIsNone(data)
        self.assertTrue(error)
