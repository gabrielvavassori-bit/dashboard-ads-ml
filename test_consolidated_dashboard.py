import unittest
import re
import json
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
                       "totalRevenue": revenue, "investment": investment, "adsRevenue": 30,
                       "units": 2, "orders": 2}],
        }

    def test_combines_only_exact_window_and_uses_weighted_tacos(self):
        result = consolidated.combine([self.account(1, 100, 10), self.account(2, 300, 60)],
                                      "2026-10-01", "2026-10-02")
        self.assertTrue(result["complete"])
        self.assertEqual(result["sums"]["revenue"], 400)
        self.assertAlmostEqual(result["sums"]["tacos"], 70 / 400)
        self.assertEqual([row["revenue"] for row in result["chart"]], [200, 200])
        self.assertEqual(len(consolidated.build_identity_tree(result["items"])), 1)

    def test_missing_sku_does_not_invent_global_family_identity(self):
        items = [
            {"account_id": 1, "account": "A", "familyId": "F1", "familyName": "Familia",
             "code": "MLB1", "totalRevenue": 10},
            {"account_id": 1, "account": "A", "familyId": "F1", "familyName": "Familia",
             "code": "MLB2", "totalRevenue": 20},
            {"account_id": 2, "account": "B", "familyId": "F1", "familyName": "Familia",
             "code": "MLB3", "totalRevenue": 30},
            {"account_id": 1, "account": "A", "code": "MLB4", "totalRevenue": 40},
        ]
        roots = consolidated.build_identity_tree(items)
        self.assertEqual(len(roots), 4)
        self.assertEqual(sorted(row["totalRevenue"] for row in roots), [10, 20, 30, 40])
        self.assertTrue(all(row["confidence"] == "listing_only" for row in roots))

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
        self.assertEqual(len(consolidated.build_identity_tree(first["items"] + second["items"])), 1)

    def test_product_table_scrolls_inside_a_bounded_frame_with_first_column_fixed(self):
        page = consolidated.render(
            [{"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": "A"}],
            {1}, {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
            [self.account(1, 100, 10)], [],
        )
        self.assertIn('class="scroll hierarchy-scroll" role="region" tabindex="0"', page)
        self.assertIn('.hierarchy-scroll{max-width:100%;max-height:min(65vh,640px);overflow:auto;', page)
        self.assertIn('.item-table th:first-child,.item-table td:first-child{position:sticky;left:0;', page)
        self.assertIn('.item-table th:first-child{z-index:3;background:#eef2f7}', page)
        self.assertIn('.item-table tbody tr.hierarchy-child-row{background:#f8faff}', page)

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

    def test_partial_official_returns_are_visible_without_certifying_total(self):
        links = [
            {"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": ""},
            {"id": 2, "client_id": "b", "official_store": "Variety", "nickname": ""},
        ]
        first, variety = self.account(1, 100, 10), self.account(2, 300, 60)
        first["kpis"].update({"returnsAvailable": True, "returnsAmount": 20,
                              "returnsOrdersAvailable": True, "returnsOrdersCount": 2})
        variety["kpis"].update({"returnsAvailable": False, "returnsAmount": None,
                                "returnsOrdersAvailable": False, "returnsOrdersCount": None,
                                "returnsObservedPartial": True, "returnsObservedAmount": 35,
                                "returnsObservedOrdersCount": 3})
        result = consolidated.combine([first, variety], "2026-10-01", "2026-10-02")
        self.assertIsNone(result["sums"]["returnsAmount"])
        self.assertIsNone(result["sums"]["returnsOrdersCount"])
        self.assertEqual(result["sums"]["returnsObservedAmount"], 55)
        self.assertEqual(result["sums"]["returnsObservedOrdersCount"], 5)
        page = consolidated.render(links, {1, 2},
                                   {"dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                                   [first, variety], [])
        self.assertIn("DEVOLUÇÕES OBSERVADAS (PARCIAL, 2/2 CONTAS; NÃO É TOTAL)", page)
        self.assertIn("R$ 55,00", page)
        self.assertIn("PEDIDOS DEVOLVIDOS OBSERVADOS (PARCIAL, 2/2 CONTAS; NÃO É TOTAL)", page)
        self.assertNotIn("DEVOLUÇÕES CONFIRMADAS</small><strong>R$ 55,00", page)

    def test_projection_preserves_only_validated_partial_returns_from_individual_view(self):
        link = {"id": 2, "client_id": "varietyshop1-1985", "official_store": "Variety", "nickname": ""}
        dashboard = {
            "meta": {"period": {"dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
                     "onlineMode": {"complete": True, "periodMatch": True}},
            "kpis": {"returnsAvailable": False, "returnsObservedPartial": True,
                     "returnsObservedAmount": 35, "returnsObservedOrdersCount": 3},
            "accountDailySeries": [{"date": "2026-10-01", "partial": False},
                                   {"date": "2026-10-02", "partial": False}],
        }
        projected = consolidated.project_account(link, dashboard)
        self.assertEqual(projected["kpis"]["returnsObservedAmount"], 35)
        self.assertEqual(projected["kpis"]["returnsObservedOrdersCount"], 3)
        self.assertIsNone(projected["kpis"]["returnsAmount"])

    def test_unknown_returns_or_wrong_period_are_never_silently_zero(self):
        first, unknown = self.account(1, 100, 10), self.account(2, 300, 60)
        first["kpis"].update({"returnsAvailable": True, "returnsAmount": 20})
        unknown["period"] = ("2026-09-01", "2026-09-02")
        sums = consolidated.combine([first, unknown], "2026-10-01", "2026-10-02")["sums"]
        self.assertIsNone(sums["returnsAmount"])
        self.assertEqual(sums["returnsObservedAmount"], 20)
        self.assertEqual(sums["returnsObservedAmountAccounts"], 1)
        first["kpis"].clear()
        sums = consolidated.combine([first, unknown], "2026-10-01", "2026-10-02")["sums"]
        self.assertIsNone(sums["returnsObservedAmount"])

    def test_account_namespace_applies_below_global_parent(self):
        items = [
            {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 10},
            {"account_id": 2, "account": "B", "code": "MLB1", "sku": "SKU",
             "familyId": "F", "userProductId": "U", "campaignId": "C", "totalRevenue": 20},
        ]
        roots = consolidated.build_identity_tree(items)
        self.assertEqual(len(roots), 1)
        self.assertEqual({child["account_id"] for child in roots[0]["children"]}, {1, 2})
        self.assertEqual(roots[0]["totalRevenue"], 30)

    def test_global_sku_parent_then_account_family_mlbu_mlb(self):
        rows = [
            {"account_id": 1, "account": "VARIETYSHOP1", "code": "MLB5001816208",
             "sku": "4093 AREIA- 42", "skuIsReference": True,
             "familyId": "F1", "userProductId": "MLBU1", "title": "Anúncio A",
             "totalRevenue": 100, "orders": 2, "units": 2, "investment": 10, "adsRevenue": 30},
            {"account_id": 2, "account": "LIMA_SHOP_PREMIUM", "code": "MLB3923370735",
             "sku": "4093 AREIA- 42", "skuIsReference": True,
             "familyId": "F2", "userProductId": "MLBU2", "title": "Anúncio B",
             "totalRevenue": 200, "orders": 3, "units": 3, "investment": 20, "adsRevenue": 40},
        ]
        roots = consolidated.build_identity_tree(rows)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["confidence"], "last_sale_reference")
        self.assertEqual(roots[0]["totalRevenue"], 300)
        self.assertEqual(roots[0]["accountCount"], 2)
        self.assertEqual({child["account"] for child in roots[0]["children"]},
                         {"VARIETYSHOP1", "LIMA_SHOP_PREMIUM"})
        leaf = roots[0]["children"][0]["children"][0]["children"][0]["children"][0]
        self.assertEqual(leaf["level"], "mlb")
        self.assertEqual(len(leaf["sources"]), 1)
        self.assertEqual(leaf["sources"][0]["account_id"], leaf["account_id"])

    def test_legacy_listing_skips_unregistered_family_and_mlbu(self):
        row = {"account_id": 1, "account": "VARIETYSHOP1", "code": "MLB1",
               "sku": "4093 AREIA- 42", "skuIsReference": True,
               "totalRevenue": 100, "orders": 2, "units": 2,
               "investment": 10, "adsRevenue": 30}
        root = consolidated.build_identity_tree([row])[0]
        self.assertEqual([child["level"] for child in root["children"]], ["account"])
        self.assertEqual([child["level"] for child in root["children"][0]["children"]], ["mlb"])
        self.assertEqual(root["children"][0]["totalRevenue"], 100)

    def test_exact_daily_receipts_supply_listing_visits_and_seven_day_trends(self):
        from datetime import date, timedelta
        period = ("2026-10-01", "2026-10-30")
        rows = [{"date": (date(2026, 10, 1) + timedelta(days=i)).isoformat(),
                 "partial": False, "orders": 1, "revenue": 10, "visits": 5}
                for i in range(30)]
        link = {"id": 1, "client_id": "client", "official_store": "Conta", "nickname": ""}
        data = {"meta": {"period": {"dateFrom": period[0], "dateTo": period[1]},
                         "onlineMode": {"complete": True, "periodMatch": True}},
                "accountDailySeries": rows,
                "items": [{"code": "MLB1", "totalRevenue": 300, "orders": 30,
                           "salesCoverageComplete": True, "visitsCoverageComplete": True,
                           "dailySeries": rows}]}
        item = consolidated.project_account(link, data)["items"][0]
        self.assertEqual(item["visits"], 150)
        self.assertEqual(item["performance7d"]["sales"], {"complete": True, "previous": 7, "current": 7})
        self.assertEqual(item["performance7d"]["visits"], {"complete": True, "previous": 35, "current": 35})
        data["items"][0]["totalRevenue"] = 310
        unverified = consolidated.project_account(link, data)["items"][0]
        self.assertNotIn("sales", unverified.get("performance7d") or {})
        data["items"][0]["visitsCoverageComplete"] = False
        unverified = consolidated.project_account(link, data)["items"][0]
        self.assertIsNone(unverified["visits"])
        self.assertNotIn("visits", unverified.get("performance7d") or {})

    def test_seven_day_metrics_require_daily_receipts_or_matching_source_window(self):
        from datetime import date, timedelta
        period = ("2026-10-01", "2026-10-30")
        rows = [{"date": (date(2026, 10, 1) + timedelta(days=i)).isoformat(),
                 "partial": False, "orders": 1, "revenue": 10, "visits": 5}
                for i in range(30) if i != 25]
        link = {"id": 1, "client_id": "client", "official_store": "Conta", "nickname": ""}
        source = {"date_from": "2026-10-17", "previous_to": "2026-10-23",
                  "current_from": "2026-10-24", "date_to": "2026-10-30",
                  "sales": {"complete": True, "previous": 7, "current": 6}}
        data = {"meta": {"period": {"dateFrom": period[0], "dateTo": period[1]},
                         "onlineMode": {"complete": True, "periodMatch": True}},
                "accountDailySeries": rows,
                "items": [{"code": "MLB1", "totalRevenue": 290, "orders": 29,
                           "salesCoverageComplete": True, "visitsCoverageComplete": True,
                           "dailySeries": rows, "performance7d": source}]}
        item = consolidated.project_account(link, data)["items"][0]
        self.assertEqual(item["visits"], 145)
        self.assertEqual(item["performance7d"]["sales"], source["sales"])
        self.assertNotIn("visits", item["performance7d"])
        data["items"][0]["performance7d"] = {**source, "date_to": "2026-10-29"}
        stale = consolidated.project_account(link, data)["items"][0]
        self.assertNotIn("sales", stale.get("performance7d") or {})
        data["items"][0]["dailySeries"] = []
        data["items"][0]["performance7d"] = {}
        missing = consolidated.project_account(link, data)["items"][0]
        self.assertIsNone(missing["visits"])
        self.assertEqual(missing["performance7d"], {})

    def test_identity_tree_preserves_price_and_only_complete_seven_day_trends(self):
        performance = {"date_from": "2026-10-01", "previous_to": "2026-10-07",
                       "current_from": "2026-10-08", "date_to": "2026-10-14",
                       "sales": {"complete": True, "previous": 1, "current": 2}}
        rows = [{"account_id": account_id, "account": f"Conta {account_id}",
                 "code": f"MLB{account_id}", "sku": "SKU-GLOBAL",
                 "familyId": f"F{account_id}", "userProductId": f"U{account_id}",
                 "totalRevenue": revenue, "units": units, "orders": units,
                 "investment": 1, "adsRevenue": 2, "currentPrice": price,
                 "lastSaleDate": "2026-10-14", "lastSalePrice": price,
                 "performance7d": performance if account_id == 1 else {}}
                for account_id, revenue, units, price in
                ((1, 120, 2, 60), (2, 210, 3, 70))]
        root = consolidated.build_identity_tree(rows)[0]
        self.assertEqual(root["priceMin"], 60)
        self.assertEqual(root["priceMax"], 70)
        self.assertIsNone(root["currentPrice"])
        self.assertEqual(root["avgSalePrice"], 66)
        self.assertEqual(root["performance7d"], {})
        accounts = {node["account_id"]: node for node in root["children"]}
        self.assertEqual(accounts[1]["performance7d"], performance)
        self.assertEqual(accounts[2]["performance7d"], {})

    def test_distinct_global_identity_does_not_merge_same_sku_text(self):
        rows = [{"account_id": account_id, "account": f"A{account_id}",
                 "code": f"MLB{account_id}", "sku": "SAME", "skuIsReference": False,
                 "globalProductId": product_id, "totalRevenue": 10,
                 "orders": 1, "units": 1, "investment": 1, "adsRevenue": 1}
                for account_id, product_id in ((1, "product-1"), (2, "product-2"))]
        roots = consolidated.build_identity_tree(rows)
        self.assertEqual(len(roots), 2)
        self.assertEqual({root["key"] for root in roots}, {"product:product-1", "product:product-2"})

    def test_duplicate_ads_campaign_does_not_duplicate_sales(self):
        base = {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
                "totalRevenue": 100, "orders": 2, "units": 3,
                "campaignId": "C1", "investment": 10, "adsRevenue": 20}
        rows = [base, {**base, "campaignId": "C2", "investment": 5, "adsRevenue": 9}]
        leaf = consolidated.build_identity_tree(rows)[0]["children"][0]["children"][0]
        self.assertEqual((leaf["totalRevenue"], leaf["orders"], leaf["units"]), (100, 2, 3))
        self.assertEqual((leaf["investment"], leaf["adsRevenue"]), (15, 29))
        self.assertEqual(leaf["sources"][0]["codes"], ["MLB1"])

    def test_repeated_campaign_after_another_does_not_erase_ads_totals(self):
        base = {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
                "totalRevenue": 100, "orders": 2, "units": 3, "salesRowPrimary": True,
                "campaignId": "C1", "investment": 10, "adsRevenue": 20}
        other = {**base, "salesRowPrimary": False, "totalRevenue": 0, "orders": 0,
                 "units": 0, "campaignId": "C2", "investment": 5, "adsRevenue": 9}
        roots = consolidated.build_identity_tree([base, other, other])
        leaf = roots[0]["children"][0]["children"][0]
        self.assertEqual((leaf["totalRevenue"], leaf["investment"], leaf["adsRevenue"]),
                         (100, 15, 29))

    def test_online_cache_zeroes_second_campaign_sales_without_losing_primary_receipt(self):
        primary = {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
                   "salesRowPrimary": True, "totalRevenue": 100, "orders": 2, "units": 3,
                   "campaignId": "C1", "investment": 10, "adsRevenue": 20}
        secondary = {**primary, "salesRowPrimary": False, "totalRevenue": 0,
                     "orders": 0, "units": 0, "campaignId": "C2",
                     "investment": 5, "adsRevenue": 9}
        roots = consolidated.build_identity_tree([primary, secondary])
        leaf = roots[0]["children"][0]["children"][0]
        self.assertEqual((leaf["totalRevenue"], leaf["orders"], leaf["units"]), (100, 2, 3))
        self.assertEqual((leaf["investment"], leaf["adsRevenue"]), (15, 29))
        self.assertEqual(roots[0]["totalRevenue"], 100)

    def test_primary_receipt_restores_optional_metrics_when_campaign_order_is_reversed(self):
        primary = {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
                   "salesRowPrimary": True, "totalRevenue": 100, "orders": 2, "units": 3,
                   "campaignId": "C1", "investment": 10, "adsRevenue": 20,
                   "visits": 15, "visitsCoverageComplete": True,
                   "performance7d": {"date_to": "2026-10-14", "sales": {"complete": True, "current": 2, "previous": 1}}}
        secondary = {**primary, "salesRowPrimary": False, "totalRevenue": 0,
                     "orders": 0, "units": 0, "campaignId": "C2",
                     "investment": 5, "adsRevenue": 9, "visits": None,
                     "visitsCoverageComplete": False, "performance7d": {}}
        leaf = consolidated.build_identity_tree([secondary, primary])[0]["children"][0]["children"][0]
        self.assertEqual(leaf["totalRevenue"], 100)
        self.assertEqual(leaf["visits"], 15)
        self.assertTrue(leaf["visitsKnown"])
        self.assertEqual(leaf["performance7d"], primary["performance7d"])

    def test_conflicting_primary_sales_rows_are_not_silently_added(self):
        primary = {"account_id": 1, "account": "A", "code": "MLB1", "sku": "SKU",
                   "salesRowPrimary": True, "totalRevenue": 100, "orders": 2, "units": 3,
                   "campaignId": "C1", "investment": 10, "adsRevenue": 20}
        conflict = {**primary, "totalRevenue": 80, "campaignId": "C2"}
        roots = consolidated.build_identity_tree([primary, conflict])
        self.assertIsNone(roots[0]["totalRevenue"])

    def test_missing_optional_metric_is_not_zero_and_null_daily_blocks_complete(self):
        account = self.account(1, 100, 10)
        account["daily"][1]["revenue"] = None
        result = consolidated.combine([account], "2026-10-01", "2026-10-02")
        self.assertFalse(result["complete"])
        self.assertIsNone(result["chart"][1]["revenue"])
        for key in ("organicRevenue", "adsNoSales", "investmentNoAdsSales", "visits"):
            self.assertIsNone(result["sums"][key])

    def test_five_and_two_account_subsets_exclude_unselected_accounts(self):
        accounts = [self.account(i, i * 100, i * 10) for i in range(1, 6)]
        full = consolidated.combine(accounts, "2026-10-01", "2026-10-02")
        subset = consolidated.combine(accounts[:2], "2026-10-01", "2026-10-02")
        three = consolidated.combine(accounts[1:4], "2026-10-01", "2026-10-02")
        self.assertEqual(full["sums"]["revenue"], 1500)
        self.assertEqual(subset["sums"]["revenue"], 300)
        self.assertEqual(three["sums"]["revenue"], 900)
        self.assertEqual(full["sums"]["orders"], 10)
        self.assertEqual(subset["sums"]["orders"], 4)
        self.assertEqual({item["account_id"] for item in subset["items"]}, {1, 2})
        self.assertEqual({item["account_id"] for item in three["items"]}, {2, 3, 4})

    def test_item_or_daily_mismatch_blocks_certified_aggregate(self):
        item_mismatch = self.account(1, 100, 10)
        item_mismatch["items"][0]["totalRevenue"] = 90
        result = consolidated.combine([item_mismatch], "2026-10-01", "2026-10-02")
        self.assertFalse(result["complete"])
        self.assertIn("itens_divergentes_revenue", result["reconciliation_issues"])

        daily_mismatch = self.account(1, 100, 10)
        daily_mismatch["daily"][0]["revenue"] = 45
        result = consolidated.combine([daily_mismatch], "2026-10-01", "2026-10-02")
        self.assertFalse(result["complete"])
        self.assertIn("serie_divergente_revenue", result["reconciliation_issues"])

    def test_unreconciled_item_field_does_not_become_zero(self):
        account = self.account(1, 100, 10)
        account["items"][0]["adsRevenue"] = None
        result = consolidated.combine([account], "2026-10-01", "2026-10-02")
        self.assertFalse(result["complete"])
        self.assertIn("itens_sem_adsRevenue", result["reconciliation_issues"])

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
        self.assertIn('https://example.com/product.jpg', page)
        self.assertIn('id="detail-backdrop"', page)
        self.assertIn('id="detail-chart-modes"', page)
        self.assertIn('id="detail-tooltip"', page)
        self.assertIn("['Visitas',g.visitsKnown?fmt(g.visits):'N/D']", page)
        self.assertIn("['Vendas nos últimos 7 dias'", page)
        self.assertIn("['Conversão nos últimos 7 dias'", page)
        self.assertIn("['Preço da última venda'", page)
        self.assertIn("['Data da última venda'", page)
        self.assertIn('formatLastSale(g.lastSaleDate)', page)
        self.assertIn('formatLastSale(node.lastSaleDate)', page)
        if shutil.which('node'):
            formatter = page.split('function formatLastSale(value){', 1)[1].splitlines()[0]
            script = ('function formatLastSale(value){' + formatter + '\n'
                      + 'console.log(JSON.stringify(['
                      + 'formatLastSale("2026-10-14"),'
                      + 'formatLastSale("2026-11-10T02:25:00.000-04:00"),'
                      + 'formatLastSale(null)]))')
            values = json.loads(subprocess.run(['node', '-e', script], capture_output=True,
                                               text=True, check=True).stdout)
            self.assertEqual(values[0], '14/10/2026')
            self.assertIn('10/11/2026', values[1])
            self.assertIn('03:25', values[1])
            self.assertEqual(values[2], 'N/D')
        self.assertIn("['revenue','Faturamento']", page)
        self.assertIn("['investment','Investimento']", page)
        self.assertIn("['tacos','TACOS']", page)
        self.assertIn('coverage.sales[day.date]!==true', page)
        self.assertIn('coverage.ads[day.date]!==true', page)
        self.assertIn('id="chart-tooltip"', page)
        self.assertIn("points:segment.join(' ')", page)
        self.assertIn("r.tacosBaseRevenue>0?r.investment/r.tacosBaseRevenue", page)
        self.assertIn("tip.appendChild(line)", page)
        self.assertIn('/online/consolidado/item-daily?', page)
        self.assertIn("Math.abs(dailySum('revenue')-g.totalRevenue)>0.01", page)
        self.assertIn("Math.abs(dailySum('adsRevenue')-g.adsRevenue)>0.01", page)
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

    @unittest.skipUnless(shutil.which("node"), "Node.js required for hierarchy mode test")
    def test_missing_family_and_mlbu_still_show_legacy_mlb_in_each_mode(self):
        page = consolidated.render(
            [{"id": 1, "client_id": "a", "official_store": "Conta A", "nickname": ""}],
            {1}, {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"},
            [self.account(1, 100, 10)], [],
        )
        function = re.search(r"function atLevel\(nodes,level\).*?(?=function visibleNodes)", page, re.S)
        self.assertIsNotNone(function)
        harness = function.group(0) + '''
        const legacy={level:'mlb',key:'MLB1',children:[]};
        const withFamily={level:'family',key:'F1',children:[{level:'mlbu',key:'U1',children:[{level:'mlb',key:'MLB2',children:[]}]}]};
        const roots=[{level:'global',key:'SKU',children:[
          {level:'account',key:'A',children:[legacy]},
          {level:'account',key:'B',children:[withFamily]}]}];
        function keys(level){return atLevel(roots,level).map(row=>row.key).sort().join(',')}
        if(keys('family')!=='F1,MLB1'||keys('mlbu')!=='MLB1,U1'||keys('mlb')!=='MLB1,MLB2'||keys('campaign')!=='MLB1,MLB2')process.exitCode=1;
        '''
        result = subprocess.run(["node"], input=harness, text=True, capture_output=True, encoding="utf-8")
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
        self.assertIn("<th>R$ 1.500,00</th><th>10</th><th>10</th><th>R$ 150,00</th><th>R$ 150,00</th><th>N/D</th><th>N/D</th><th>Completa</th>", page)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for browser comparison test")
    def test_five_previous_periods_are_summed_after_one_transient_failure(self):
        accounts = [{"id": i, "client_id": f"client-{i}",
                     "official_store": f"Conta {i}", "nickname": ""} for i in range(1, 6)]
        period = {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02",
                  "comparePeriod": {"dateFrom": "2026-09-29", "dateTo": "2026-09-30"}}
        page = consolidated.render(accounts, {1, 2, 3, 4, 5}, period,
                                   [self.account(i, i * 100, i * 10) for i in range(1, 6)], [])
        script = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', page, re.S)[-1]
        config = json.loads(re.search(r'<script type="application/json" id="comparison-request">(.*?)</script>', page).group(1))
        harness = '''
        const config=CONFIG, attempts={}, elements=[{dataset:{metric:'revenue'},textContent:'N/D'}];
        global.document={getElementById:()=>({textContent:JSON.stringify(config)}),querySelectorAll:()=>elements};
        global.fetch=async url=>{const id=Number(new URL(url,'https://example.com').searchParams.get('account_id'));
          attempts[id]=(attempts[id]||0)+1;if(id===3&&attempts[id]===1)throw new Error('transient');
          return {ok:true,status:200,json:async()=>({ok:true,period:config.period.comparePeriod,
            summary:{revenue:id*50,units:id,orders:id,investment:id,adsRevenue:id,tacosBaseRevenue:id*50}})};};
        '''.replace('CONFIG', json.dumps(config)) + script + '''
        setTimeout(()=>{if(elements[0].textContent!=='▲ +100% vs. período anterior'||attempts[3]!==2)
          {console.error(elements[0].textContent,attempts);process.exitCode=1}},100);
        '''
        result = subprocess.run(["node"], input=harness, text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
