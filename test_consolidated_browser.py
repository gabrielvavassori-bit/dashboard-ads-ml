"""Browser contract for the read-only consolidated hierarchy and daily modal."""

import json
import unittest
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from consolidated_dashboard import render

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment prerequisite
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class ConsolidatedBrowserTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.launch(headless=True)
        except Exception:
            self.playwright.stop()
            self.skipTest("Chromium is not installed")
        self.page = self.browser.new_page()

    def tearDown(self):
        if hasattr(self, "browser"):
            self.browser.close()
        if hasattr(self, "playwright"):
            self.playwright.stop()

    def _open(self, sales_second_day=True, ads_second_day=True, http_status=200,
              daily_revenue=2362.38, daily_ads_revenue=404.22,
              daily_investment=68, daily_units=11, days=2):
        dates = [(date(2026, 10, 1) + timedelta(days=offset)).isoformat()
                 for offset in range(days)]
        period = {"mode": "custom", "dateFrom": dates[0], "dateTo": dates[-1]}
        accounts = [{"id": 2, "client_id": "lima", "official_store": "LIMA_SHOP_PREMIUM", "nickname": ""}]
        projection = [{
            "id": 2, "label": "LIMA_SHOP_PREMIUM", "period": (dates[0], dates[-1]),
            "complete": True,
            "kpis": {"revenue": 2362.38, "investment": 68, "adsRevenue": 404.22,
                     "units": 11, "tacosBaseRevenue": 2362.38},
            "daily": [{"date": day, "revenue": 2362.38 if index == 0 else 0,
                       "investment": 68 if index == 0 else 0,
                       "adsRevenue": 404.22 if index == 0 else 0,
                       "units": 11 if index == 0 else 0, "partial": False}
                      for index, day in enumerate(dates)],
            "items": [{"account_id": 2, "account": "LIMA_SHOP_PREMIUM", "code": "MLB3923370735",
                       "sku": "4093 AREIA- 42", "skuIsReference": True,
                       "familyId": "F1", "familyName": "Coturno",
                       "userProductId": "MLBU1", "userProductName": "Variação areia",
                       "title": "Coturno areia 42", "totalRevenue": 2362.38, "orders": 11,
                       "units": 11, "investment": 68, "adsRevenue": 404.22}],
        }]
        html = render(accounts, {2}, period, projection, [])
        receipts = {day: (sales_second_day if index == 1 else True)
                    for index, day in enumerate(dates)}
        ads_receipts = {day: (ads_second_day if index == 1 else True)
                        for index, day in enumerate(dates)}
        payload = {"ok": True, "trace_id": "test-trace", "coverage": {"sales": receipts,
                    "ads": ads_receipts},
                   "series": {"MLB3923370735": [{"date": dates[0], "salesPresent": True,
                                "adsPresent": True, "revenue": daily_revenue, "orders": 11,
                                "units": daily_units, "adsRevenue": daily_ads_revenue,
                                "investment": daily_investment}]}}

        def route_handler(route):
            if "/item-daily?" in route.request.url:
                route.fulfill(status=http_status, content_type="application/json", body=json.dumps(payload))
            else:
                route.fulfill(status=200, content_type="text/html", body=html)

        self.page.route("https://consolidado.test/**", route_handler)
        self.page.goto("https://consolidado.test/online/consolidado")

    def test_sparse_zero_receipt_draws_real_product_graph_at_every_level(self):
        self._open()
        self.assertEqual(self.page.locator(".item-table thead th").count(), 16)
        self.assertIn("Últimos 7 dias", self.page.locator(".item-table thead").inner_text())
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('Séries certificadas')")
        self.page.locator("#detail-chart svg").wait_for()
        self.assertIn("Séries certificadas", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.page.locator("#detail-close").click()
        self.page.locator('#view-modes a[data-view="familia"]').click()
        self.assertIn("Coturno", self.page.locator("#item-rows > tr").first.inner_text())
        self.page.locator('#view-modes a[data-view="mlb"]').click()
        self.assertIn("Coturno areia 42", self.page.locator("#item-rows > tr").first.inner_text())
        self.page.locator('#view-modes a[data-view="hibrida"]').click()
        for level in ("global", "account", "family", "mlbu"):
            self.page.locator(f"#item-rows tr.level-{level} .hierarchy-toggle").first.click()
        self.assertEqual(self.page.locator("#item-rows tr.level-mlb td").count(), 16)
        self.assertIn("MLB3923370735", self.page.locator("#item-rows").inner_text())
        self.page.locator("#item-rows tr.level-mlb .detail-open").click()
        self.page.locator("#detail-chart svg").wait_for()
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.assertIn("LIMA_SHOP_PREMIUM", self.page.locator("#detail-account").inner_text())

    def test_thirty_closed_days_with_sparse_zero_receipts(self):
        self._open(days=30)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('Séries certificadas')")
        self.page.locator("#detail-chart svg").wait_for()
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.assertIn("R$ 2.362,38", self.page.locator("#detail-summary").inner_text())

    def test_network_timeout_has_distinct_reason(self):
        self._open()
        self.page.evaluate("() => { window.fetch = () => Promise.reject(new DOMException('timeout', 'AbortError')); }")
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('timeout')")
        self.assertIn("sem resposta HTTP", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)

    def test_missing_sales_receipt_never_draws_zero(self):
        self._open(sales_second_day=False)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('vendas sem recibo')")
        self.assertIn("vendas sem recibo", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)

    def test_ads_gap_does_not_hide_certified_sales_chart(self):
        self._open(ads_second_day=False)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('Vendas diárias completas')")
        self.assertIn("Vendas diárias completas", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.page.locator('#detail-chart-modes button[data-metric="investment"]').click()
        self.assertIn("N/D", self.page.locator("#detail-chart").inner_text())

    def test_sum_mismatch_keeps_chart_unavailable(self):
        self._open(daily_revenue=2360)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('soma divergente')")
        self.assertIn("soma divergente", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)

    def test_units_mismatch_keeps_chart_unavailable(self):
        self._open(daily_units=10)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('unidades ou pedidos divergentes')")
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)

    def test_ads_sum_mismatch_preserves_sales_but_hides_ads_metrics(self):
        self._open(daily_ads_revenue=400)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('soma diária de Ads divergente')")
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.page.locator('#detail-chart-modes button[data-metric="adsRevenue"]').click()
        self.assertIn("N/D", self.page.locator("#detail-chart").inner_text())

    def test_upstream_http_failures_are_not_treated_as_zero(self):
        for code in (401, 403, 429, 502):
            with self.subTest(code=code):
                self._open(http_status=code)
                self.page.get_by_role("button", name="Abrir gráfico").first.click()
                self.page.wait_for_function("code => document.querySelector('#detail-status').textContent.includes('HTTP ' + code)", arg=code)
                self.assertIn("HTTP " + str(code), self.page.locator("#detail-status").inner_text())
                self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)

    def test_five_accounts_then_two_keep_exact_selection_and_nested_graph(self):
        period = {"mode": "custom", "dateFrom": "2026-10-01", "dateTo": "2026-10-02"}
        accounts = [{"id": i, "client_id": f"client-{i}", "official_store": f"CONTA_{i}", "nickname": ""}
                    for i in range(1, 6)]
        projections = []
        failed_account = {"id": 2}
        for i in range(1, 6):
            revenue = float(i * 100)
            projections.append({
                "id": i, "label": f"CONTA_{i}", "period": (period["dateFrom"], period["dateTo"]),
                "complete": True, "kpis": {"revenue": revenue, "investment": float(i * 10),
                                              "adsRevenue": float(i * 20), "units": i,
                                              "tacosBaseRevenue": revenue},
                "daily": [{"date": period["dateFrom"], "revenue": revenue, "investment": float(i * 10),
                           "adsRevenue": float(i * 20), "units": i, "partial": False},
                          {"date": period["dateTo"], "revenue": 0, "investment": 0,
                           "adsRevenue": 0, "units": 0, "partial": False}],
                "items": [{"account_id": i, "account": f"CONTA_{i}", "code": f"MLB90000000{i}",
                           "sku": "4093 AREIA-42" if i <= 2 else f"SKU-{i}",
                           "skuIsReference": i <= 2, "familyId": f"F{i}", "familyName": f"Família {i}",
                           "userProductId": f"MLBU{i}", "userProductName": f"Variação {i}",
                           "title": f"Anúncio {i}", "totalRevenue": revenue, "orders": i,
                           "units": i, "investment": float(i * 10), "adsRevenue": float(i * 20),
                           "thumbnailUrl": "https://consolidado.test/photo.png"}],
            })

        def route_handler(route):
            parsed = urlparse(route.request.url)
            if parsed.path.endswith("/item-daily"):
                query = parse_qs(parsed.query)
                account_id = int(query["account_id"][0])
                if account_id == failed_account["id"]:
                    route.fulfill(status=502, content_type="application/json",
                                  body=json.dumps({"ok": False, "error": "agent_unavailable", "trace_id": "failed-chunk"}))
                    return
                code = f"MLB90000000{account_id}"
                body = {"ok": True, "trace_id": f"test-{account_id}",
                        "coverage": {"sales": {"2026-10-01": True, "2026-10-02": True},
                                     "ads": {"2026-10-01": True, "2026-10-02": True}},
                        "series": {code: [{"date": "2026-10-01", "salesPresent": True,
                                           "adsPresent": True, "revenue": float(account_id * 100),
                                           "orders": account_id, "units": account_id,
                                           "investment": float(account_id * 10),
                                           "adsRevenue": float(account_id * 20)}]}}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                return
            if parsed.path.endswith(".png"):
                route.fulfill(status=200, content_type="image/png", body=b"\x89PNG\r\n\x1a\n")
                return
            query = parse_qs(parsed.query)
            selected = {int(value) for value in query.get("account_id", [])} or set(range(1, 6))
            html = render(accounts, selected, period, [p for p in projections if p["id"] in selected], [])
            route.fulfill(status=200, content_type="text/html", body=html)

        self.page.route("https://consolidado.test/**", route_handler)
        self.page.goto("https://consolidado.test/online/consolidado")
        self.assertIn("R$ 1.500,00", self.page.locator(".cards").inner_text())
        self.assertIn("5 conta(s)", self.page.locator("body").inner_text())
        self.page.locator("#item-search").fill("4093 AREIA-42")
        self.assertEqual(self.page.locator("#item-rows > tr:not(.hierarchy-child-row)").count(), 1)
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.wait_for_function("document.querySelector('#detail-status').textContent.includes('HTTP 502')")
        self.assertIn("failed-chunk", self.page.locator("#detail-status").inner_text())
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 0)
        self.page.locator("#detail-close").click()
        failed_account["id"] = None
        self.page.get_by_role("button", name="Abrir gráfico").first.click()
        self.page.locator("#detail-chart svg").wait_for()
        self.assertIn("CONTA_1", self.page.locator("#detail-account").inner_text())
        self.assertIn("CONTA_2", self.page.locator("#detail-account").inner_text())
        self.assertNotIn("CONTA_3", self.page.locator("#detail-account").inner_text())
        self.page.locator("#detail-close").click()
        self.page.locator("#item-search").fill("")
        self.page.locator('input[name="account_id"]').evaluate_all(
            "inputs => inputs.forEach(input => input.checked = ['1','2'].includes(input.value))")
        self.page.get_by_role("button", name="Atualizar visão").click()
        self.assertIn("R$ 300,00", self.page.locator(".cards").inner_text())
        self.assertNotIn("CONTA_3", self.page.locator("#item-rows").inner_text())
        self.page.locator("#item-search").fill("4093 AREIA-42")
        self.assertEqual(self.page.locator("#item-rows > tr:not(.hierarchy-child-row)").count(), 1)
        for level in ("global", "account", "family", "mlbu"):
            self.page.locator(f"#item-rows tr.level-{level} .hierarchy-toggle").first.click()
        self.assertIn("CONTA_1", self.page.locator("#item-rows").inner_text())
        self.assertIn("CONTA_2", self.page.locator("#item-rows").inner_text())
        self.page.locator(".level-account .detail-open").first.click()
        detail_account = self.page.locator("#detail-account").inner_text()
        self.assertTrue("CONTA_1" in detail_account or "CONTA_2" in detail_account)
        self.assertNotIn("CONTA_3", detail_account)
        self.assertEqual(self.page.locator("#detail-chart svg").count(), 1)
        self.page.locator("#detail-close").click()
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertGreater(self.page.locator(".scroll").first.evaluate("el => el.scrollWidth"), 0)
        self.assertEqual(self.page.locator(".cards").count(), 1)


if __name__ == "__main__":
    unittest.main()
