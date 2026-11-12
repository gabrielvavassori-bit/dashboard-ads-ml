"""Regressão: histórico diário por anúncio fora da página e carregado ao abrir o detalhe."""
import json
import unittest
from unittest.mock import patch

import app

SALES = [{"item_id": "MLB1", "snapshot_date": "2026-09-07", "orders_count": 2, "units_total": 3, "revenue_total": 90.0}]
ADS = [{"item_id": "MLB1", "snapshot_date": "2026-09-07", "total_amount": 30.0, "cost": 5.0, "prints": 100, "clicks": 4}]
VISITS = [{"item_id": "MLB1", "snapshot_date": "2026-09-07", "visits_total": 12}]


class ItemDailyOnDemandTest(unittest.TestCase):
    def test_page_strips_item_and_child_series_and_flags_on_demand(self):
        data = {"items": [{"code": "MLB1", "dailySeries": [1], "children": [{"code": "MLB2", "dailySeries": [2]},
                                                                           {"code": "MLB3", "dailySeriesItemIndex": 0}]}],
                "accountDailySeries": [{"date": "2026-09-07", "partial": False}]}
        app._strip_item_daily_series(data)
        item = data["items"][0]
        self.assertNotIn("dailySeries", item)
        self.assertNotIn("dailySeries", item["children"][0])
        self.assertNotIn("dailySeriesItemIndex", item["children"][1])
        self.assertTrue(data["meta"]["itemDailyOnDemand"])
        self.assertEqual(data["accountDailySeries"], [{"date": "2026-09-07", "partial": False}])  # conta intacta

    def test_on_demand_series_equals_page_builder_series(self):
        _by_date, expected = app._daily_series_by_item(SALES, ADS, VISITS, False)
        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(SALES, {}, "")) as s, \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=(ADS, {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=(VISITS, {}, "")):
            out = app._item_daily_payload("c", ["MLB1"], "2026-09-07", "2026-10-06", False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["series"]["MLB1"], expected["MLB1"])
        self.assertEqual(s.call_args.args[3], "MLB1")  # filtro chega ao agente

    def test_financial_reader_failure_is_unavailable_never_zero(self):
        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], {}, "snapshots_diarios_indisponiveis")), \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=(ADS, {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=(VISITS, {}, "")):
            out = app._item_daily_payload("c", ["MLB1"], "2026-09-07", "2026-10-06", False)
        self.assertFalse(out["ok"])
        self.assertNotIn("series", out)

    def test_sparse_zero_requires_explicit_daily_receipts(self):
        receipts = {"2026-09-07": {"complete": True, "source": "observed"},
                    "2026-09-08": {"complete": True, "source": "explicit_zero"},
                    "2026-09-09": {"complete": False},
                    "2026-09-10": {"complete": True, "error": "source_unavailable"}}
        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(SALES, receipts, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=(ADS, receipts, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=(VISITS, {}, "")):
            out = app._item_daily_payload("c", ["MLB1"], "2026-09-07", "2026-09-10", False)
        self.assertEqual(out["coverage"]["sales"], {
            "2026-09-07": True, "2026-09-08": True,
            "2026-09-09": False, "2026-09-10": False})
        self.assertEqual(out["coverage"]["ads"], out["coverage"]["sales"])
        self.assertFalse(any(row["date"] == "2026-09-08" for row in out["series"]["MLB1"]))

    def test_trace_records_account_period_codes_and_empty_response_without_financial_values(self):
        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=([], {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=([], {}, "")), \
             patch("builtins.print") as output:
            response = app._item_daily_payload("varietyshop1-1985", ["MLB1", "MLB2"],
                                               "2026-10-07", "2026-11-05", False)
        self.assertTrue(response["ok"])
        self.assertEqual(response["series"], {"MLB1": [], "MLB2": []})
        line = output.call_args.args[0]
        self.assertTrue(line.startswith("[item-daily-trace] "))
        event = json.loads(line.split(" ", 1)[1])
        self.assertEqual(event["trace_id"], response["trace_id"])
        self.assertEqual(event["client_id"], "varietyshop1-1985")
        self.assertEqual((event["date_from"], event["date_to"]), ("2026-10-07", "2026-11-05"))
        self.assertEqual(event["requested_codes"], ["MLB1", "MLB2"])
        self.assertEqual(event["response"]["codes_without_series"], ["MLB1", "MLB2"])
        self.assertEqual(event["response"]["codes_absent_from_sources"], ["MLB1", "MLB2"])

    def test_trace_distinguishes_source_code_mismatch_and_sanitizes_error(self):
        other_sales = [{**SALES[0], "item_id": "MLB9"}]
        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(other_sales, {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=([], {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=([], {}, "")), \
             patch("builtins.print") as output:
            response = app._item_daily_payload("c", ["MLB1"], "2026-09-07", "2026-10-06", False)
        event = json.loads(output.call_args.args[0].split(" ", 1)[1])
        self.assertEqual(event["sources"]["sales"]["normalized_codes"], ["MLB9"])
        self.assertEqual(event["response"]["codes_absent_from_sources"], ["MLB1"])
        self.assertNotIn("90.0", output.call_args.args[0])
        self.assertEqual(response["series"]["MLB1"], [])

        with patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], {}, "token=secret")), \
             patch.object(app, "_sales_intelligence_fetch_daily_ads", return_value=([], {}, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_visits", return_value=([], {}, "")), \
             patch("builtins.print") as output:
            response = app._item_daily_payload("c", ["MLB1"], "2026-09-07", "2026-10-06", False)
        event = json.loads(output.call_args.args[0].split(" ", 1)[1])
        self.assertFalse(response["ok"])
        self.assertEqual(event["response"]["error"], "unclassified")
        self.assertNotIn("secret", output.call_args.args[0])

    def test_empty_item_filter_is_not_sent_to_agent(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value={"ok": True, "rows": []}) as f:
            app._sales_intelligence_fetch_daily_sales("c", "2026-09-07", "2026-10-06")
        self.assertEqual(f.call_args.args[1].get("item_ids"), "")  # removido por _fetch_dash_ads_json (vazio)

    def test_frontend_loads_series_on_detail_open(self):
        import gerar_dashboard_ads_ml as g
        src = open(g.__file__, encoding="utf-8").read()
        self.assertIn("/online/item-daily?", src)
        self.assertIn("Nenhum zero foi inventado", src)
        self.assertIn("loadItemDaily(item).then", src)


if __name__ == "__main__":
    unittest.main()
