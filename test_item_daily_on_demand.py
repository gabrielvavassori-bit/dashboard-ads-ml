"""Regressão: histórico diário por anúncio fora da página e carregado ao abrir o detalhe."""
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
