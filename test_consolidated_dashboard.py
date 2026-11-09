import unittest
import re
import shutil
import subprocess

import consolidated_dashboard as consolidated


class ConsolidatedMathTests(unittest.TestCase):
    def account(self, account_id, revenue, investment, complete=True):
        return {
            "id": account_id, "label": f"Conta {account_id}", "period": ("2026-10-01", "2026-10-02"),
            "complete": complete,
            "kpis": {"revenue": revenue, "investment": investment, "adsRevenue": 30,
                     "units": 2, "tacosBaseRevenue": revenue},
            "daily": [
                {"date": "2026-10-01", "revenue": revenue / 2, "investment": investment / 2,
                 "adsRevenue": 15, "units": 1, "partial": not complete},
                {"date": "2026-10-02", "revenue": revenue / 2, "investment": investment / 2,
                 "adsRevenue": 15, "units": 1, "partial": not complete},
            ],
            "items": [{"code": f"MLB{account_id}", "sku": "MESMO-SKU", "title": "Produto",
                       "totalRevenue": revenue, "investment": investment, "units": 2, "orders": 2}],
        }

    def test_combines_only_exact_window_and_uses_weighted_tacos(self):
        result = consolidated.combine([self.account(1, 100, 10), self.account(2, 300, 60)],
                                      "2026-10-01", "2026-10-02")
        self.assertTrue(result["complete"])
        self.assertEqual(result["sums"]["revenue"], 400)
        self.assertAlmostEqual(result["sums"]["tacos"], 70 / 400)
        self.assertEqual([row["revenue"] for row in result["chart"]], [200, 200])
        self.assertEqual(len(consolidated._group_items(result["items"], "sku")), 2)

    def test_hybrid_groups_family_but_keeps_unrelated_listings_separate(self):
        items = [
            {"account_id": 1, "account": "A", "familyId": "F1", "familyName": "Familia",
             "code": "MLB1", "totalRevenue": 10},
            {"account_id": 1, "account": "A", "familyId": "F1", "familyName": "Familia",
             "code": "MLB2", "totalRevenue": 20},
            {"account_id": 2, "account": "B", "familyId": "F1", "familyName": "Familia",
             "code": "MLB3", "totalRevenue": 30},
            {"account_id": 1, "account": "A", "code": "MLB4", "totalRevenue": 40},
        ]
        groups = consolidated._group_items(items, "hibrida")
        self.assertEqual(len(groups), 3)
        self.assertEqual(sorted(row["totalRevenue"] for row in groups), [30, 30, 40])

    def test_missing_day_or_partial_account_never_certifies_chart(self):
        partial = self.account(2, 300, 60, complete=False)
        partial["daily"].pop()
        result = consolidated.combine([self.account(1, 100, 10), partial],
                                      "2026-10-01", "2026-10-02")
        self.assertFalse(result["complete"])
        self.assertTrue(result["chart"][1]["missing"])

    def test_other_window_is_not_silently_summed(self):
        other = self.account(2, 300, 60)
        other["period"] = ("2026-09-01", "2026-09-02")
        result = consolidated.combine([self.account(1, 100, 10), other],
                                      "2026-10-01", "2026-10-02")
        self.assertEqual(result["accepted"], 1)
        self.assertFalse(result["complete"])

    def test_failed_account_cannot_make_subset_chart_look_complete(self):
        accounts = [
            {"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": "A"},
            {"id": 2, "client_id": "b", "official_store": "Conta B", "nickname": "B"},
        ]
        period = {"dateFrom": "2026-10-01", "dateTo": "2026-10-02"}
        page = consolidated.render(accounts, {1, 2}, period, [self.account(1, 100, 10)], ["Conta B"])
        self.assertIn("Visão incompleta", page)
        self.assertIn("Gráfico N/D", page)
        self.assertNotIn("Faturamento diário consolidado", page)

    def test_full_operational_view_keeps_account_identity_and_weighted_ratios(self):
        accounts = [
            {"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": "A"},
            {"id": 2, "client_id": "b", "official_store": "Conta B", "nickname": "B"},
        ]
        first, second = self.account(1, 100, 10), self.account(2, 300, 60)
        first["items"][0]["account"] = "Conta A"
        second["items"][0]["account"] = "Conta B"
        first["items"][0]["account_id"] = 1
        second["items"][0]["account_id"] = 2
        first["kpis"]["organicRevenue"] = 70
        second["kpis"]["organicRevenue"] = 270
        page = consolidated.render(accounts, {1, 2},
                                   {"dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                   [first, second], [])
        for label in ("TACOS GERAL", "ACOS ADS", "ROAS ADS", "Família", "Variação/MLBU",
                      "MLB", "SKU", "Campanha", "Conta A", "Conta B", "Desempenho diário das contas"):
            self.assertIn(label, page)
        self.assertIn("17,50%", page)
        self.assertIn("116,67%", page)
        self.assertIn("0,86x", page)
        self.assertEqual(len(consolidated._group_items(first["items"] + second["items"], "sku")), 2)

    def test_unknown_visits_never_become_zero(self):
        first = self.account(1, 100, 10)
        second = self.account(2, 300, 60)
        result = consolidated.combine([first, second], "2026-10-01", "2026-10-02")
        self.assertIsNone(result["sums"]["visits"])
        self.assertIsNone(result["chart"][0]["visits"])

    def test_official_visits_and_cancellations_require_every_account(self):
        accounts = []
        for account_id in (1, 2):
            data = self.account(account_id, 100, 10)
            data["accountMetrics"] = {
                "visits": {"complete": True, "total": 12},
                "cancelledOrders": {"complete": True, "total": account_id},
            }
            for row in data["daily"]:
                row["visits"] = 6
            link = {"id": account_id, "client_id": str(account_id),
                    "official_store": f"Conta {account_id}", "nickname": ""}
            dashboard = {"meta": {"period": {"dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                  "onlineMode": {"complete": True, "periodMatch": True}},
                         "kpis": data["kpis"], "items": data["items"],
                         "accountDailySeries": data["daily"], "accountMetrics": data["accountMetrics"]}
            accounts.append(consolidated.project_account(link, dashboard))
        result = consolidated.combine(accounts, "2026-10-01", "2026-10-02")
        self.assertEqual(result["sums"]["visits"], 24)
        self.assertEqual(result["sums"]["cancelledOrders"], 3)
        self.assertEqual([row["visits"] for row in result["chart"]], [12, 12])
        accounts[1]["cancelled_orders"] = None
        self.assertIsNone(consolidated.combine(accounts, "2026-10-01", "2026-10-02")["sums"]["cancelledOrders"])

    def test_account_namespace_applies_to_every_grouping(self):
        items = [
            {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 10},
            {"account_id": 2, "account": "B", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 20},
        ]
        for mode in ("hibrida", "familia", "variacao", "mlb", "sku", "campanha"):
            self.assertEqual(len(consolidated._group_items(items, mode)), 2, mode)

    def test_photo_detail_and_period_stay_on_consolidated_page(self):
        accounts = [{"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": ""}]
        first = self.account(1, 100, 10)
        first["items"][0].update({"account": "Conta A", "account_id": 1,
                                  "thumbnailUrl": "https://example.com/product.jpg"})
        page = consolidated.render(accounts, {1},
                                   {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                   [first], [])
        self.assertIn('name="period"', page)
        self.assertIn('value="custom" selected', page)
        self.assertIn('src="https://example.com/product.jpg"', page)
        self.assertIn('id="detail-backdrop"', page)
        self.assertIn('/online/consolidado/item-daily?', page)
        self.assertIn('Math.abs(dailyTotal-g.totalRevenue)>0.01', page)
        self.assertIn('"account_id":1', page)
        self.assertNotIn('src="javascript:', page)
        self.assertIn('Conferência por conta', page)
        self.assertIn('Soma das contas selecionadas', page)
        self.assertIn('period=custom&amp;date_from=2026-10-01&amp;date_to=2026-10-02', page)
        if shutil.which("node"):
            scripts = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', page, re.S)
            for script in scripts:
                if script.lstrip().startswith("(function") or script.lstrip().startswith("(async function"):
                    result = subprocess.run(["node", "--check"], input=script, text=True, capture_output=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_uncertified_account_is_not_presented_as_certified_total(self):
        accounts = [
            {"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": ""},
            {"id": 2, "client_id": "b", "official_store": "Conta B", "nickname": ""},
        ]
        first = self.account(1, 100, 10)
        second = self.account(2, 300, 60, complete=False)
        page = consolidated.render(accounts, {1, 2},
                                   {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                   [first, second], [])
        self.assertIn("Não certificada", page)
        self.assertIn("Visão incompleta", page)
        self.assertIn("Soma das contas selecionadas", page)
        self.assertIn("<th>N/D</th><th>N/D</th><th>Não certificada</th>", page)

    def test_five_selected_accounts_reconcile_without_touching_individual_views(self):
        accounts = [{"id": i, "client_id": f"client-{i}",
                     "official_store": f"Conta {i}", "nickname": ""} for i in range(1, 6)]
        projections = [self.account(i, i * 100, i * 10) for i in range(1, 6)]
        page = consolidated.render(accounts, {1, 2, 3, 4, 5},
                                   {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                   projections, [])
        for i in range(1, 6):
            self.assertIn(f"Conta {i}</td><td>2026-10-01 a 2026-10-02</td>", page)
        self.assertIn("<th>R$ 1.500,00</th><th>R$ 150,00</th><th>Completa</th>", page)


if __name__ == "__main__":
    unittest.main()
