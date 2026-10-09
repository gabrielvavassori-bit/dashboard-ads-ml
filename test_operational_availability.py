import copy
import unittest
from unittest.mock import patch
import app
from gerar_dashboard_ads_ml import render_dashboard


class OperationalAvailabilityTests(unittest.TestCase):
    def test_exact_committed_financial_rows_upgrade_operational_period(self):
        from test_online_periods import complete_integrity_contract, active_snapshot_completeness_rule
        payload = self.payload()
        committed = copy.deepcopy(payload)
        committed.pop("operational_partial")
        committed.update(complete_integrity_contract("demo", "7", "2026-09-01", "2026-09-02"))
        committed["latest"]["sales"]["complete"] = True
        committed["ads"]["items"][0]["status"] = "active"
        payload["committed_period"] = committed
        with patch.object(app, "_fetch_dash_ads_json", return_value=payload), patch.object(
            app, "_load_snapshot_completeness_governance_rule",
            return_value=active_snapshot_completeness_rule(),
        ):
            result, error = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertEqual(error, "")
            self.assertFalse(result["operational_partial"])
            self.assertTrue(result["latest"]["sales"]["complete"])
            self.assertEqual(result["ads"]["items"][0]["status"], "active")
            payload["sales"]["items"]["MLB999"] = {
                "orders_count": 0, "units_total": 0, "revenue_total": 0,
            }
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertFalse(result["operational_partial"])
            payload["sales"]["items"]["MLB999"]["revenue_total"] = 0.01
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertTrue(result["operational_partial"])
            del payload["sales"]["items"]["MLB999"]
            committed["ads"]["items"][0]["cost"] = 11
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertTrue(result["operational_partial"])
            committed["ads"]["items"][0]["cost"] = 10
            committed["sales"]["items"]["MLB123"]["revenue_total"] = 21
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertTrue(result["operational_partial"])
            committed["sales"]["items"]["MLB123"]["revenue_total"] = 20
            committed["ads"]["items"][0] = None
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertTrue(result["operational_partial"])

    def test_status_overlay_is_generic_for_existing_and_future_accounts(self):
        from test_online_periods import complete_integrity_contract, active_snapshot_completeness_rule
        for client_id in ("conta-existente-generica", "conta-futura-generica"):
            with self.subTest(client_id=client_id):
                payload = self.payload(client_id)
                committed = copy.deepcopy(payload)
                committed.pop("operational_partial")
                committed.update(complete_integrity_contract(
                    client_id, "7", "2026-09-01", "2026-09-02"
                ))
                committed["latest"]["sales"]["complete"] = True
                committed["ads"]["items"][0].update(
                    status="active", ad_group_id="grupo-apenas-no-commit",
                    cost=999, total_amount=999,
                )
                payload["committed_period"] = committed
                with patch.object(app, "_fetch_dash_ads_json", return_value=payload), patch.object(
                    app, "_load_snapshot_completeness_governance_rule",
                    return_value=active_snapshot_completeness_rule(),
                ):
                    result, error = app._dash_ads_fetch_operational_latest(
                        client_id, "7", "2026-09-01", "2026-09-02"
                    )
                self.assertEqual(error, "")
                self.assertTrue(result["chart_period_verified"])
                self.assertEqual(result["ads"]["items"][0]["status"], "active")
                self.assertEqual(result["ads"]["items"][0]["cost"], 10)
                self.assertEqual(result["ads"]["items"][0]["total_amount"], 40)

    def test_committed_period_is_scoped_and_partial_fallback_preserved(self):
        from test_online_periods import complete_integrity_contract, active_snapshot_completeness_rule
        payload = self.payload()
        committed = copy.deepcopy(payload)
        committed.pop("operational_partial")
        committed.update(complete_integrity_contract("demo", "7", "2026-09-01", "2026-09-02"))
        committed["latest"]["sales"]["complete"] = True
        payload["ads"]["items"][0].update(title="Original product", family_id="family-original", thumbnail="original.jpg")
        committed["ads"]["items"][0].update(
            status="active", title="Committed title", ad_group_id="group-only-in-commit",
            cost=999, total_amount=999,
        )
        payload["committed_period"] = committed
        with patch.object(app, "_fetch_dash_ads_json", return_value=payload), patch.object(
            app, "_load_snapshot_completeness_governance_rule", return_value=active_snapshot_completeness_rule()
        ):
            result, error = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertEqual(error, "")
            self.assertTrue(result["chart_period_verified"])
            self.assertEqual(result["ads"]["items"][0]["family_id"], "family-original")
            self.assertEqual(result["ads"]["items"][0]["title"], "Original product")
            self.assertEqual(result["ads"]["items"][0]["status"], "active")
            self.assertEqual(result["ads"]["items"][0]["cost"], 10)
            self.assertTrue(result["operational_partial"])
            committed["sales"]["items"]["MLB123"]["revenue_total"] = 50
            from test_online_periods import complete_daily_coverage
            coverage = complete_daily_coverage("2026-09-01", "2026-09-02")
            with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(
                [dict(item_id="MLB123", snapshot_date="2026-09-01", revenue_total=50, units_total=1, orders_count=1)], coverage, ""
            )), patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=(
                [dict(item_id="MLB123", snapshot_date="2026-09-01", total_amount=40, cost=10)], coverage, ""
            )):
                data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
            self.assertEqual(error, "")
            self.assertTrue(data["accountDailySeries"])
            self.assertTrue(all(not row["partial"] for row in data["accountDailySeries"]))
            self.assertEqual(data["items"][0]["familyId"], "family-original")
            self.assertEqual(data["items"][0]["thumbnailUrl"], "original.jpg")
            self.assertEqual(data["items"][0]["campaignStatus"], "Ativa")
            for field, value in (("client_id", "other"), ("advertiser_id", "8")):
                previous = committed["integrity_contract"]["identity"][field]
                committed["integrity_contract"]["identity"][field] = value
                result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
                self.assertIs(result, payload)
                committed["integrity_contract"]["identity"][field] = previous
            committed["integrity_contract"]["requested_period"]["date_to"] = "2026-09-03"
            result, _ = app._dash_ads_fetch_operational_latest("demo", "7", "2026-09-01", "2026-09-02")
            self.assertIs(result, payload)

    def payload(self, client_id="demo"):
        identity = dict(client_id=client_id, advertiser_id="7", date_from="2026-09-01", date_to="2026-09-02")
        return dict(ok=True, operational_partial=True, client_id=client_id, period_cache_hit=True,
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
        self.assertEqual(len(data["accountDailySeries"]), 2)
        self.assertTrue(all(row["partial"] and not row["salesPresent"] and not row["adsPresent"]
                            for row in data["accountDailySeries"]))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args_list[0].args[0], "/internal/dash-ads/operational-cache")
        self.assertEqual(fetch.call_args_list[1].args[0], "/internal/dash-ads/visits-daily")
        self.assertEqual(fetch.call_args_list[2].args[0], "/internal/dash-ads/returns-summary")

    def test_partial_cache_still_reads_independent_returns(self):
        returns = {
            "ok": True, "complete": True,
            "date_from": "2026-09-01", "date_to": "2026-09-02",
            "amount": 12.50, "returns_count": 1,
            "returned_orders_count": 1, "orders_total": 10,
            "orders_total_available": True,
        }
        with patch.object(app, "_fetch_dash_ads_json", side_effect=[self.payload(), {}, returns]) as fetch:
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        self.assertTrue(data["kpis"]["returnsAvailable"])
        self.assertTrue(data["kpis"]["returnsOrdersAvailable"])
        self.assertEqual(data["kpis"]["returnsAmount"], 12.50)
        self.assertEqual(fetch.call_args_list[2].args[0], "/internal/dash-ads/returns-summary")

    def test_confirmed_returned_orders_count_remains_visible_without_order_universe(self):
        returns = {
            "ok": True, "complete": True,
            "date_from": "2026-09-01", "date_to": "2026-09-02",
            "amount": 12.50, "returns_count": 1,
            "returned_orders_count": 2, "orders_total_available": False,
        }
        with patch.object(app, "_fetch_dash_ads_json", side_effect=[self.payload(), {}, returns]):
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

    def test_partial_daily_values_preserved_with_source_presence(self):
        payload = self.payload()
        payload["daily_sales"] = [dict(item_id="MLB123", snapshot_date="2026-09-01",
                                       revenue_total=20, units_total=1, orders_count=1)]
        payload["daily_ads"] = [dict(item_id="MLB123", snapshot_date="2026-09-02",
                                     total_amount=40, cost=10)]
        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, error = app._build_online_dashboard_data("demo", "7", "2026-09-01", "2026-09-02")
        self.assertEqual(error, "")
        first, second = data["accountDailySeries"]
        self.assertEqual(first["revenue"], 20)
        self.assertEqual(second["adsRevenue"], 40)
        self.assertEqual(second["investment"], 10)
        self.assertTrue(first["partial"] and second["partial"])
        self.assertTrue(first["salesPresent"])
        self.assertFalse(first["adsPresent"])
        self.assertFalse(second["salesPresent"])
        self.assertTrue(second["adsPresent"])
        html = render_dashboard(data)
        self.assertIn("chartMetricAvailable", html)
        self.assertIn("N/D — sem dados", html)
        self.assertIn("hasPartial ? '' : averageLine", html)
        self.assertIn("hasPartial ? '' : smoothChartPath(points)", html)

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
