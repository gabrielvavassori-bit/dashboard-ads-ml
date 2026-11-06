import unittest

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

    def test_account_namespace_applies_to_every_grouping(self):
        items = [
            {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 10},
            {"account_id": 2, "account": "B", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 20},
        ]
        for mode in ("hibrida", "familia", "variacao", "mlb", "sku", "campanha"):
            self.assertEqual(len(consolidated._group_items(items, mode)), 2, mode)


if __name__ == "__main__":
    unittest.main()
