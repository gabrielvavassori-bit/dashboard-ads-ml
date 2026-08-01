import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app
from gerar_dashboard_ads_ml import render_dashboard


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


class OnlinePeriodTests(unittest.TestCase):
    def test_closed_presets_end_yesterday(self):
        expected = {
            "7": ("2026-07-24", "2026-07-30"),
            "15": ("2026-07-16", "2026-07-30"),
            "30": ("2026-07-01", "2026-07-30"),
            "yesterday": ("2026-07-30", "2026-07-30"),
        }
        for mode, dates in expected.items():
            with self.subTest(mode=mode):
                period = app._resolve_online_period(mode, now=NOW)
                self.assertEqual((period["dateFrom"], period["dateTo"]), dates)
                self.assertFalse(period["partial"])

    def test_quick_presets_do_not_require_month_or_comparison(self):
        period = app._resolve_online_period("7", month="", compare="", now=NOW)
        self.assertEqual((period["dateFrom"], period["dateTo"]), ("2026-07-24", "2026-07-30"))
        self.assertEqual(period["compareMode"], "none")
        self.assertIsNone(period["comparePeriod"])

    def test_today_current_month_custom_and_comparisons(self):
        today = app._resolve_online_period("today", compare="none", now=NOW)
        self.assertEqual((today["dateFrom"], today["dateTo"]), ("2026-07-31", "2026-07-31"))
        self.assertTrue(today["partial"])

        month = app._resolve_online_period("month", month="2026-07", compare="previous_month", now=NOW)
        self.assertEqual((month["dateFrom"], month["dateTo"]), ("2026-07-01", "2026-07-30"))
        self.assertEqual((month["comparePeriod"]["dateFrom"], month["comparePeriod"]["dateTo"]), ("2026-06-01", "2026-06-30"))

        custom = app._resolve_online_period("custom", date_from="2026-06-10", date_to="2026-06-19", compare="previous_year", now=NOW)
        self.assertEqual((custom["dateFrom"], custom["dateTo"]), ("2026-06-10", "2026-06-19"))
        self.assertEqual((custom["comparePeriod"]["dateFrom"], custom["comparePeriod"]["dateTo"]), ("2025-06-10", "2025-06-19"))

    def test_online_builder_forwards_selected_period_and_reports_match(self):
        calls = []
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-24", "date_to": "2026-07-30", "updated_at": "2026-07-31T12:00:00-03:00", "sales": {"complete": True}},
            "ads": {
                "date_from": "2026-07-24",
                "date_to": "2026-07-30",
                "items_total": 1,
                "items": [{
                    "item_id": "MLB123",
                    "campaign_id": "C1",
                    "status": "active",
                    "sku": "SKU-1",
                    "title": "Produto de teste",
                    "cost": "10",
                    "total_amount": "100",
                    "direct_amount": "80",
                    "prints": "1000",
                    "clicks": "10",
                    "units_quantity": "1",
                    "price": "100",
                }],
            },
            "sales": {"items": {"MLB123": {"revenue_total": "120", "units_total": "2"}}},
        }

        def fake_fetch(path, params):
            calls.append((path, params))
            return payload

        requested = app._resolve_online_period("7", compare="previous", now=NOW)
        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            data, error = app._build_online_dashboard_data("cliente-teste", "adv-1", requested["dateFrom"], requested["dateTo"], requested)

        self.assertEqual(error, "")
        self.assertTrue(calls)
        self.assertTrue(all(params["date_from"] == "2026-07-24" and params["date_to"] == "2026-07-30" for _, params in calls))
        self.assertTrue(data["meta"]["onlineMode"]["periodMatch"])
        self.assertEqual(data["onlineBeta"]["requestedPeriod"]["dateFrom"], "2026-07-24")
        self.assertEqual(data["onlineBeta"]["apiPeriod"]["dateTo"], "2026-07-30")

    def test_dashboard_contains_beta_period_controls(self):
        period = app._resolve_online_period("7", compare="previous", now=NOW)
        self.assertTrue(callable(app._build_online_dashboard_data))
        html = render_dashboard({"meta": {"onlineMode": {"enabled": True, "onlinePeriod": period}}, "onlineBeta": {"enabled": True, "requestedPeriod": period}, "items": []})
        self.assertIn('data-online-period', html)
        self.assertIn('data-online-period-form', html)
        self.assertIn('id="period-month-field"', html)
        self.assertIn('id="period-custom-fields"', html)
        self.assertIn('Nao comparar', html)
        self.assertIn("Ultimos 7 dias", html)


if __name__ == "__main__":
    unittest.main()
