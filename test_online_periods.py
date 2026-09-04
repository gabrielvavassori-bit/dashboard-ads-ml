import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app
from gerar_dashboard_ads_ml import aggregate_by_sku, render_dashboard


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


class OnlinePeriodTests(unittest.TestCase):
    def test_sales_intelligence_bootstrap_is_ninety_closed_days(self):
        period = app._sales_intelligence_default_period(NOW)
        self.assertEqual(period["dateFrom"], "2026-05-02")
        self.assertEqual(period["dateTo"], "2026-07-30")
        self.assertEqual(period["label"], "Ultimos 90 dias fechados")

    def test_sales_intelligence_opening_does_not_start_a_full_history_refresh(self):
        source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
        builder = source.split("def _build_sales_intelligence_memory_data", 1)[1].split(
            "def _inject_sales_intelligence_memory_data", 1
        )[0]
        self.assertNotIn("online-cache-refresh", builder)

    def test_sku_view_keeps_children_available_for_separate_mlbu_boxes(self):
        base = {
            "sku": "SKU-1", "title": "Produto", "campaign": "Campanha",
            "orders": 1, "units": 1, "productRevenue": 10, "totalRevenue": 10,
            "tacosBaseRevenue": 10, "adsRevenue": 5, "adsDirectRevenue": 5,
            "organicRevenue": 5, "investment": 1, "impressions": 10,
            "clicks": 2, "adsSales": 1, "lastPrice": 10, "avgSalePrice": 10,
        }
        rows = aggregate_by_sku([
            {**base, "code": "MLB1", "userProductId": "MLBU-A"},
            {**base, "code": "MLB2", "userProductId": "MLBU-A"},
            {**base, "code": "MLB3", "userProductId": "MLBU-B"},
        ])

        self.assertEqual(len(rows), 1)
        self.assertEqual([item["code"] for item in rows[0]["children"]], ["MLB1", "MLB2", "MLB3"])

    def test_dashboard_has_grouped_layout_zoom_help_and_whatsapp_support(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        self.assertIn('function groupedSkuBodies(rows)', source)
        self.assertIn('productParentRow(productParentSummary(group.children))', source)
        self.assertIn('data-view-mode="family"', source)
        self.assertIn('data-view-mode="hybrid"', source)
        self.assertIn("let currentViewMode = 'hybrid'", source)
        self.assertIn('data-view-mode="variation"', source)
        self.assertIn('function groupedFamilyBodies(rows)', source)
        self.assertIn('data-abc-mode="family"', source)
        self.assertIn('data-abc-mode="hybrid"', source)
        self.assertIn("let abcMode = 'hybrid'", source)
        self.assertIn('data-abc-mode="variation"', source)
        self.assertIn('function abcSourceRows()', source)
        self.assertIn('function splitHybrid(rows)', source)
        self.assertIn('function groupedHybridBodies(rows)', source)
        self.assertIn("const displayedCount = currentViewMode === 'hybrid'", source)
        self.assertIn('return sortedGroups(splitByFamily(rows))', source)
        self.assertIn('itemSearchText(item).includes(q)', source)
        self.assertIn('function groupedVariationBodies(rows)', source)
        self.assertIn('function groupedMlbBodies(rows)', source)
        self.assertIn('id="tableZoomFit"', source)
        self.assertIn('id="tableHelpText"', source)
        self.assertIn('https://wa.me/5511998397385?', source)
        self.assertIn('Oi%2C%20estou%20precisando%20de%20suporte%20no%20Dash%20Ads.', source)
        self.assertIn('<option value="priceAboveAvg">Preco acima da media &gt; 5%</option>', source)
        self.assertIn('function priceAboveAverageRatio(item)', source)
        self.assertIn('return priceAboveAverageRatio(item) > threshold;', source)
        self.assertIn('const above = ratio > 0;', source)
        self.assertIn("if (context === 'priceAboveAvg') return hasPriceAboveAverage(item, 0.05);", source)
        self.assertIn('.price-above-avg', source)

    def test_online_builder_keeps_campaign_condition_and_catalog_links_separate(self):
        payload = {
            "ok": True,
            "latest": {
                "date_from": "2026-08-04",
                "date_to": "2026-08-10",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-04",
                "date_to": "2026-08-10",
                "items_total": 2,
                "items": [
                    {
                        "item_id": "MLB5399002228",
                        "campaign_id": "CAMP-1",
                        "campaign_name": "Campanha principal",
                        "thumbnail_url": "http://http2.mlstatic.com/condition-a.jpg",
                        "sku": "LAZ-7X4",
                        "title": "Condicao A",
                        "cost": 10,
                        "total_amount": 100,
                        "direct_amount": 80,
                        "prints": 1000,
                        "clicks": 20,
                        "units_quantity": 5,
                        "price": 269.99,
                        "price_effective": 229.97,
                        "regular_price": 269.99,
                    },
                    {
                        "item_id": "MLB6689184622",
                        "campaign_id": "CAMP-2",
                        "campaign_name": "Campanha secundaria",
                        "sku": "LAZ-7X4",
                        "title": "Condicao B",
                        "cost": 5,
                        "total_amount": 40,
                        "direct_amount": 30,
                        "prints": 500,
                        "clicks": 10,
                        "units_quantity": 2,
                        "price": 78.98,
                    },
                ],
            },
            "sales": {
                "date_from": "2026-08-04",
                "date_to": "2026-08-10",
                "items": {
                    "MLB5399002228": {
                        "revenue_total": 500,
                        "orders_count": 4,
                        "units_total": 5,
                        "family_id": "FAM-7X4",
                        "family_name": "Familia 7x4",
                        "user_product_id": "MLBU-7X4",
                        "user_product_name": "Variacao 7x4",
                        "catalog_product_id": "CAT-7X4",
                        "catalog_listing": True,
                    },
                    "MLB6689184622": {
                        "revenue_total": 631.84,
                        "orders_count": 1,
                        "units_total": 8,
                        "family_id": "FAM-7X4",
                        "family_name": "Familia 7x4",
                        "user_product_id": "MLBU-7X4",
                        "user_product_name": "Variacao 7x4",
                        "catalog_product_id": "CAT-7X4",
                        "catalog_listing": True,
                    },
                },
            },
        }

        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, error = app._build_online_dashboard_data(
                "conta-ativa",
                "adv-1",
                "2026-08-04",
                "2026-08-10",
                {"dateFrom": "2026-08-04", "dateTo": "2026-08-10"},
            )

        self.assertEqual(error, "")
        self.assertEqual({item["campaignId"] for item in data["items"]}, {"CAMP-1", "CAMP-2"})
        self.assertTrue(all(item["familyId"] == "FAM-7X4" for item in data["items"]))
        self.assertTrue(all(item["familyName"] == "Familia 7x4" for item in data["items"]))
        self.assertTrue(all(item["userProductId"] == "MLBU-7X4" for item in data["items"]))
        self.assertTrue(all(item["userProductName"] == "Variacao 7x4" for item in data["items"]))
        self.assertTrue(all(item["conditionCount"] == 2 for item in data["items"]))
        self.assertTrue(all(item["catalogProductId"] == "CAT-7X4" for item in data["items"]))
        self.assertEqual(data["items"][0]["thumbnailUrl"], "http://http2.mlstatic.com/condition-a.jpg")
        self.assertEqual({item["campaign"] for item in data["items"]}, {"Campanha principal", "Campanha secundaria"})
        condition_a = next(item for item in data["items"] if item["code"] == "MLB5399002228")
        self.assertEqual(condition_a["currentPrice"], 229.97)
        condition_b = next(item for item in data["items"] if item["code"] == "MLB6689184622")
        self.assertEqual(condition_b["orders"], 1)
        self.assertEqual(condition_b["units"], 8)

        html = render_dashboard(data)
        self.assertIn("Campanha Ads", html)
        self.assertIn("Condicao/opcao de venda", html)
        self.assertIn("Pedidos", html)
        self.assertIn("Unidades", html)
        self.assertIn("MLBU-7X4", html)
        self.assertIn("Catalogo CAT-7X4", html)
        self.assertIn("product-thumbnail", html)
        self.assertIn("if (parsed.protocol === 'http:') parsed.protocol = 'https:';", html)

    def test_beta_product_diagnostics_keeps_prices_daily_history_and_read_only_preview(self):
        latest_payload = {
            "ok": True,
            "latest": {
                "date_from": "2026-08-07",
                "date_to": "2026-08-13",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-07",
                "date_to": "2026-08-13",
                "items": [{
                    "item_id": "MLB5364060738",
                    "campaign_id": "CAMP-1",
                    "sku": "BA00463",
                    "title": "Kit Espatulas",
                    "price": 34.90,
                    "listing_type_id": "gold_pro",
                    "logistic_type": "fulfillment",
                    "free_shipping": True,
                    "fast_shipping": True,
                    "cost": 12,
                    "total_amount": 100,
                    "direct_amount": 80,
                    "prints": 1000,
                    "clicks": 50,
                    "units_quantity": 5,
                }],
            },
            "campaigns": {"campaigns": [{
                "campaign_id": "CAMP-1",
                "campaign_budget": 50,
                "target_roas": 12,
                "observed_fields": ["campaign_budget", "target_roas"],
            }]},
            "sales": {
                "date_from": "2026-08-07",
                "date_to": "2026-08-13",
                "items": {"MLB5364060738": {
                    "revenue_total": 388.70,
                    "orders_count": 13,
                    "units_total": 13,
                    "last_sale_date": "2026-08-11T12:00:00-03:00",
                    "last_price": 29.90,
                }},
            },
        }
        daily_payload = {
            "ok": True,
            "rows": [
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-11", "orders_count": 1, "units_total": 1, "revenue_total": 29.90, "last_price": 29.90},
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-12", "orders_count": 0, "units_total": 0, "revenue_total": 0},
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-13", "orders_count": 0, "units_total": 0, "revenue_total": 0},
            ],
        }
        daily_ads_payload = {
            "ok": True,
            "rows": [{
                "item_id": "MLB5364060738", "snapshot_date": "2026-08-11",
                "campaign_id": "CAMP-1", "cost": 10, "total_amount": 50,
                "direct_amount": 40, "indirect_amount": 10,
                "prints": 100, "clicks": 5, "units_quantity": 2,
            }],
        }

        def fetch(path, params=None):
            if path == "/internal/dash-ads/sales-daily":
                return daily_payload
            if path == "/internal/dash-ads/ads-daily":
                return daily_ads_payload
            return latest_payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, error = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-07", "2026-08-13",
                {"dateFrom": "2026-08-07", "dateTo": "2026-08-13"},
            )

        self.assertEqual(error, "")
        item = data["items"][0]
        self.assertEqual(item["currentPrice"], 34.90)
        self.assertEqual(item["lastSalePrice"], 29.90)
        self.assertAlmostEqual(item["priceChangePct"], (34.90 - 29.90) / 29.90)
        self.assertEqual(item["suggestedTestPrice"], 32.90)
        self.assertEqual(item["listingTypeId"], "gold_pro")
        self.assertEqual(item["logisticType"], "fulfillment")
        self.assertTrue(item["freeShipping"])
        self.assertTrue(item["fastShipping"])
        self.assertEqual(item["campaignBudget"], 50)
        self.assertEqual(item["campaignTargetRoas"], 12)
        self.assertEqual([row["date"] for row in item["dailySeries"]], ["2026-08-11", "2026-08-12", "2026-08-13"])
        self.assertEqual(item["dailySeries"][0]["adsRevenue"], 50)
        self.assertEqual(item["dailySeries"][0]["investment"], 10)
        self.assertEqual(item["dailySeries"][0]["tacosBaseRevenue"], 39.90)

        html = render_dashboard(data)
        self.assertIn("Vendas diarias do periodo", html)
        self.assertIn('data-chart-metric="revenue"', html)
        self.assertIn('data-chart-metric="adsRevenue"', html)
        self.assertIn('data-chart-metric="investment"', html)
        self.assertIn('data-chart-metric="roas"', html)
        self.assertIn('data-chart-metric="tacos"', html)
        self.assertIn('data-chart-metric="units"', html)
        self.assertIn('data-chart-metric="orders"', html)
        self.assertIn('data-chart-metric="price"', html)
        self.assertIn("chart-average-line", html)
        self.assertIn("Media do periodo", html)
        self.assertIn("Orcamento medio diario", html)
        self.assertIn("ROAS objetivo", html)
        self.assertIn("ROAS realizado", html)
        self.assertIn("TACOS realizado", html)
        self.assertIn("chart-reference-line", html)
        self.assertIn("if (metric === 'tacos') return {min:0, max:.15}", html)
        self.assertIn("Array.from({length:16}", html)
        self.assertIn("chart-extreme-marker", html)
        self.assertIn("tooltip.style.top = '10px'", html)
        self.assertIn("Frete gratis e rapido", html)
        self.assertIn("Frete por conta do comprador", html)
        self.assertIn("Condicao comercial do anuncio", html)
        self.assertIn("PREVIA SOMENTE LEITURA", html)
        self.assertIn("Esta etapa nao cria promocao, nao altera preco e nao envia comandos", html)

    def test_governance_summary_reads_authenticated_central_bundle(self):
        bundle = {
            "version": "2026-08-10",
            "sha256": "abc123",
            "published_at": "2026-08-10T12:00:00Z",
            "required_files": ["global_rules.json", "shared_rules.json"],
            "files": {
                "global_rules.json": {"rules": [{"id": "RULE-1", "description": "Regra global"}]},
                "shared_rules.json": {"rules": [{"id": "RULE-2", "description": "Regra compartilhada"}]},
                "shared_human_decisions.json": {"decisions": [{
                    "id": "UNC-1", "description": "Decisao", "status": "E",
                    "classification": "GLOBAL", "source_project": "Un Clic",
                }]},
                "marketplace_knowledge.json": {"entries": [{
                    "id": "MK-AGML-ADS-RULE-CATALOG-INTAKE", "description": "Conhecimento",
                }]},
            },
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(bundle).encode("utf-8")

        with patch.dict(app.os.environ, {"GOVERNANCE_READ_API_KEY": "secret"}), \
             patch.object(app, "urlopen", return_value=FakeResponse()) as mocked_urlopen:
            payload, status = app._fetch_governance_summary()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["central_rules_count"], 2)
        self.assertEqual(payload["shared_human_decisions_count"], 1)
        self.assertEqual(payload["project_decisions"][0]["id"], "UNC-1")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://marketplace-governance-hub.onrender.com/v1/bundle")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_governance_summary_fails_closed_without_read_key(self):
        with patch.dict(app.os.environ, {}, clear=False):
            app.os.environ.pop("GOVERNANCE_READ_API_KEY", None)
            payload, status = app._fetch_governance_summary()
        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])

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
            "sales": {
                "date_from": "2026-07-24",
                "date_to": "2026-07-30",
                "items": {"MLB123": {"revenue_total": "120", "units_total": "2"}},
            },
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
        snapshot = data["meta"]["onlineMode"]["snapshot"]
        self.assertEqual(snapshot["snapshotAt"], "2026-07-31T12:00:00-03:00")
        self.assertEqual(snapshot["snapshotSource"], "agente-ml / online-cache-latest")
        self.assertTrue(snapshot["requestedAt"])
        self.assertIsInstance(snapshot["snapshotAgeSeconds"], int)
        self.assertEqual(data["onlineBeta"]["snapshot"], snapshot)

    def test_online_builder_does_not_refresh_cache_outside_selected_period(self):
        stale_payload = {
            "ok": True,
            "latest": {
                "date_from": "2026-07-31",
                "date_to": "2026-07-31",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-07-31",
                "date_to": "2026-07-31",
                "items_total": 1,
                "items": [{
                    "item_id": "MLB123",
                    "title": "Produto teste",
                    "cost": "10",
                    "total_amount": "100",
                    "direct_amount": "80",
                    "prints": "100",
                    "clicks": "10",
                    "units_quantity": "1",
                    "price": "100",
                }],
            },
            "sales": {"items": {"MLB123": {"revenue_total": "120", "units_total": "2"}}},
        }
        calls = []

        def fake_fetch(path, params):
            calls.append((path, params.copy()))
            return stale_payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            data, message = app._build_online_dashboard_data(
                client="conta-ativa",
                advertiser_id="123",
                date_from="2026-07-24",
                date_to="2026-07-30",
                requested_period={"dateFrom": "2026-07-24", "dateTo": "2026-07-30"},
            )
        self.assertIsNone(data)
        self.assertIn("fora do periodo", message)
        self.assertEqual(
            [path for path, _ in calls],
            [
                "/internal/dash-ads/online-cache-latest",
                "/internal/dash-ads/online-cache-refresh",
                "/internal/dash-ads/online-cache-latest",
            ],
        )

    def test_online_builder_rejects_ads_from_a_different_period(self):
        mixed_payload = {
            "ok": True,
            "period_cache_hit": True,
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-07-19",
                "date_to": "2026-08-17",
                "items": [{"item_id": "MLB1", "cost": 15123.85, "total_amount": 103081.91}],
            },
            "sales": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": {"MLB1": {"revenue_total": 51234.19}},
            },
        }

        with patch.object(app, "_fetch_dash_ads_json", return_value=mixed_payload):
            data, message = app._build_online_dashboard_data(
                "varietyshop1",
                "adv-1",
                "2026-08-11",
                "2026-08-17",
                {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"},
            )

        self.assertIsNone(data)
        self.assertIn("fora do periodo", message)

    def test_online_builder_reports_pending_while_period_refresh_runs(self):
        stale_payload = {
            "ok": True,
            "period_cache_hit": False,
            "latest": {
                "date_from": "2026-07-24",
                "date_to": "2026-07-30",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-07-24",
                "date_to": "2026-07-30",
                "items": [{"item_id": "MLB123", "cost": 1, "total_amount": 2}],
            },
            "sales": {"items": {}},
        }

        def fake_fetch(path, _params):
            if path.endswith("online-cache-refresh"):
                return {"ok": True, "status": "running", "http_status": 202}
            return stale_payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            data, message = app._build_online_dashboard_data(
                client="conta-ativa",
                date_from="2026-07-24",
                date_to="2026-07-30",
                requested_period={"dateFrom": "2026-07-24", "dateTo": "2026-07-30"},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_PENDING_PREFIX))
        html = app.templates.render_online_cache_pending(
            message[len(app.ONLINE_CACHE_PENDING_PREFIX):],
        )
        self.assertIn("Preparando o periodo selecionado", html)
        self.assertIn("window.location.reload", html)

    def test_sales_intelligence_injection_uses_real_final_body_tag(self):
        html = "<html><body><script>var sample = '</body>';</script><div>ok</div></body></html>"
        injected = app._inject_sales_intelligence_memory_data(html, {
            "clientName": "Cliente teste",
            "sales": [],
            "imports": [],
            "events": [],
        })
        self.assertEqual(injected.count('<script id="salesIntelligenceBootstrap"'), 1)
        self.assertIn("var sample = '</body>';", injected)
        self.assertTrue(injected.endswith("</body></html>"))
        self.assertGreater(
            injected.rfind("salesIntelligenceBootstrap"),
            injected.rfind("<div>ok</div>"),
        )
        self.assertIn("window.__marketplaceAppReady.then(applyData)", injected)

    def test_sales_intelligence_uses_daily_snapshots_without_detailed_order_scan(self):
        latest = {
            "sales": {"items": {"MLB123": {
                "sku": "SKU-123",
                "title": "Produto teste",
                "units_total": 3,
                "revenue_total": 150,
            }}},
            "ads": {"items": []},
        }
        daily = [{
            "item_id": "MLB123",
            "snapshot_date": "2026-08-10",
            "orders_count": 2,
            "units_total": 3,
            "revenue_total": 150,
        }]
        user = {"name": "Cliente", "email": "cliente@example.com"}
        link = {"client_id": "cliente", "advertiser_id": "1", "official_store": "Loja", "nickname": ""}

        with patch.object(app, "_sales_intelligence_fetch_latest", return_value=(latest, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(daily, "")), \
             patch.object(app, "_sales_intelligence_fetch_orders") as detailed_fetch:
            data, message = app._build_sales_intelligence_memory_data(user, link)

        self.assertEqual(message, "")
        detailed_fetch.assert_not_called()
        self.assertEqual(len(data["sales"]), 1)
        self.assertEqual(data["sales"][0]["ordersCount"], 2)
        self.assertEqual(data["sales"][0]["units"], 3)
        self.assertEqual(data["sales"][0]["productRevenue"], 150)
        self.assertEqual(data["sales"][0]["sku"], "SKU-123")

    def test_sales_intelligence_reports_pending_while_hourly_refresh_runs(self):
        stale_payload = {
            "ok": True,
            "period_cache_hit": False,
            "status": {"status": "running"},
            "latest": {
                "date_from": "2026-07-24",
                "date_to": "2026-08-22",
            },
            "ads": {
                "date_from": "2026-07-24",
                "date_to": "2026-08-22",
                "items": [],
            },
            "sales": {
                "date_from": "2026-07-24",
                "date_to": "2026-08-22",
                "items": {},
            },
        }

        calls = []

        def fake_fetch(path, _params):
            calls.append(path)
            return stale_payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa",
                "adv-1",
                "2026-04-30",
                "2026-08-26",
            )

        self.assertIsNone(payload)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_PENDING_PREFIX))
        self.assertEqual(calls, [
            "/internal/dash-ads/online-cache-latest",
            "/internal/dash-ads/online-cache-latest",
        ])

    def test_sales_intelligence_reports_pending_when_hourly_snapshot_is_not_ready(self):
        empty_payload = {
            "ok": True,
            "period_cache_hit": False,
            "latest": {},
            "ads": {},
            "sales": {},
        }

        with patch.object(app, "_fetch_dash_ads_json", return_value=empty_payload) as fetch:
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa",
                "adv-1",
                "2026-08-28",
                "2026-09-03",
            )

        self.assertIsNone(payload)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_PENDING_PREFIX))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args_list[0].args, (
            "/internal/dash-ads/online-cache-latest",
            {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-28", "date_to": "2026-09-03"},
        ))
        self.assertEqual(fetch.call_args_list[-1].args, (
            "/internal/dash-ads/online-cache-latest",
            {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-28", "date_to": "2026-09-03", "fallback": "latest_complete_7d"},
        ))

    def test_sales_intelligence_accepts_exact_partial_snapshot_while_backfill_runs(self):
        partial_payload = {
            "ok": True,
            "period_cache_hit": True,
            "period_cache_complete": False,
            "latest": {"date_from": "2026-08-28", "date_to": "2026-09-03"},
            "ads": {"date_from": "2026-08-28", "date_to": "2026-09-03", "items": []},
            "sales": {"date_from": "2026-08-28", "date_to": "2026-09-03", "items": {}},
        }
        with patch.object(app, "_fetch_dash_ads_json", return_value=partial_payload) as fetch:
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa", "adv-1", "2026-08-28", "2026-09-03"
            )

        self.assertEqual(message, "")
        self.assertIs(payload, partial_payload)
        self.assertEqual(fetch.call_count, 2)

    def test_sales_intelligence_opens_latest_complete_window_while_requested_range_refreshes(self):
        requested = {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-05", "date_to": "2026-09-03"}
        fallback = {
            "ok": True,
            "period_cache_hit": True,
            "period_cache_complete": True,
            "fallback": {
                "reason": "latest_complete_7d",
                "requested": {"date_from": "2026-08-05", "date_to": "2026-09-03"},
                "served": {"date_from": "2026-08-16", "date_to": "2026-08-22"},
            },
            "latest": {"date_from": "2026-08-16", "date_to": "2026-08-22"},
            "ads": {"date_from": "2026-08-16", "date_to": "2026-08-22", "items": []},
            "sales": {"date_from": "2026-08-16", "date_to": "2026-08-22", "items": {}},
        }

        def fake_fetch(path, params):
            if path.endswith("online-cache-refresh"):
                return {"ok": True, "status": "running"}
            if params.get("fallback"):
                return fallback
            return {"ok": True, "period_cache_hit": False, "latest": {}, "ads": {}, "sales": {}}

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa", "adv-1", requested["date_from"], requested["date_to"]
            )

        self.assertEqual(message, "")
        self.assertIs(payload, fallback)
        self.assertEqual(payload["background_refresh"]["status"], "running")

    def test_sales_intelligence_falls_back_to_aggregate_cache_when_daily_snapshot_fails(self):
        latest = {
            "sales": {"items": {"MLB123": {
                "sku": "SKU-123", "title": "Produto teste", "units_total": 1, "revenue_total": 50,
                "orders_count": 1, "last_sale_date": "2026-08-10T12:00:00-03:00",
            }}},
            "ads": {"items": []},
        }
        user = {"name": "Cliente", "email": "cliente@example.com"}
        link = {"client_id": "cliente", "advertiser_id": "1", "official_store": "Loja", "nickname": ""}

        with patch.object(app, "_sales_intelligence_fetch_latest", return_value=(latest, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], "worker_timeout")):
            data, message = app._build_sales_intelligence_memory_data(user, link)

        self.assertEqual(message, "")
        self.assertEqual(len(data["sales"]), 1)
        self.assertEqual(data["sales"][0]["ordersCount"], 1)
        self.assertEqual(data["sales"][0]["units"], 1)
        self.assertEqual(data["sales"][0]["productRevenue"], 50)
        self.assertEqual(data["sales"][0]["sku"], "SKU-123")
        self.assertIn("fallback", data["onlineNotice"].lower())

    def test_sales_intelligence_asset_counts_aggregated_daily_orders(self):
        source = Path(__file__).with_name("assets").joinpath("inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        self.assertIn("function orderCountOf(sale)", source)
        self.assertIn("const orders = sumOrderCount(rows);", source)
        self.assertIn("window.__marketplaceAppReady = boot();", source)

    def test_profit_view_uses_separate_financial_store_after_online_hydration(self):
        source = Path(__file__).with_name("assets").joinpath("inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        boot = source.split("async function boot()", 1)[1].split("async function loadGovernanceSummary", 1)[0]
        memory_hydration = source.split("setMemoryData:", 1)[1].split("createDemoSales,", 1)[0]
        financial_source = source.split("function financialSalesSource()", 1)[1].split("function profitWindowedSales", 1)[0]
        financial_loader = source.split("async function loadRemoteOrderFinancials()", 1)[1].split("async function reloadRemoteOrderFinancials", 1)[0]

        self.assertIn("financialSales: []", source)
        self.assertIn("createObjectStore('financialSales'", source)
        self.assertIn("state.financialSales = detailed;", source)
        self.assertIn("const salesList = Array.isArray(salesScope) ? salesScope : financialSalesSource();", source)
        self.assertIn("!String(sale?.saleNumber || '').startsWith('daily:')", source)
        self.assertIn("return stored.filter(isDedicatedFinancialSale);", financial_source)
        self.assertIn("...(r.packIds ? [...r.packIds] : [])", source)
        self.assertIn("if (s.packId) row.packIds.add(s.packId);", source)
        self.assertNotIn("state.sales.filter", financial_source)
        self.assertIn("const window = reportWindowData();", financial_loader)
        self.assertIn("date_from=${dateFrom}&date_to=${dateTo}", financial_loader)
        self.assertNotIn("state.sales.map", financial_loader)
        self.assertNotIn("loadRemoteOrderFinancials()", boot)
        self.assertNotIn("persistSaleCostLedger(state.sales)", boot)
        self.assertIn("reloadRemoteOrderFinancials();", memory_hydration)
        self.assertNotIn("clearStore('saleCosts')", memory_hydration)

    def test_financial_view_uses_billing_components_and_exposes_pack_relationship(self):
        source = Path(__file__).with_name("assets").joinpath("inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        mapper = source.split("function remoteFinancialSale(row)", 1)[1].split("function allocatePackShipping", 1)[0]
        financial_base = source.split("function financialBase(sale)", 1)[1].split("function saleOrderKey", 1)[0]
        detail = source.split("function renderProfitDetail", 1)[1].split("function renderMonthly", 1)[0]

        self.assertIn("selling_fee_gross", mapper)
        self.assertIn("promotion_subsidy", mapper)
        self.assertIn("shipping_fee_allocated", mapper)
        self.assertIn("shippingNetAlreadyAllocated", mapper)
        self.assertIn("buyerPriceIncrease: installmentEquivalent", mapper)
        self.assertIn("installmentFee: -installmentEquivalent", mapper)
        self.assertIn("commissionRate", mapper)
        self.assertIn("categoryPath", mapper)
        self.assertIn("shippingSubsidy", mapper)
        self.assertNotIn("shippingSubsidy", financial_base)
        self.assertIn("sale?.shippingNetAlreadyAllocated ? 0 : Number(sale?.shippingRevenue || 0)", financial_base)
        self.assertIn("Pacote/carrinho", detail)
        self.assertIn("Venda/item", detail)
        self.assertIn("Comissão %", detail)
        self.assertIn("Subsídio/benefício", detail)

    def test_online_builder_uses_requested_period_when_explicit_dates_are_empty(self):
        payload = {
            "ok": True,
            "latest": {
                "date_from": "2026-07-03",
                "date_to": "2026-08-01",
                "updated_at": "2026-08-02T09:00:00-03:00",
                "sales": {"complete": True},
            },
        "ads": {
            "date_from": "2026-07-03",
            "date_to": "2026-08-01",
            "items_total": 1,
            "items": [{
                "item_id": "MLB123",
                "campaign_id": "C1",
                "campaign_name": "Campanha teste",
                "status": "active",
                "sku": "SKU-123",
                "title": "Produto teste",
                "cost": "10",
                "total_amount": "20",
                "direct_amount": "15",
                "units_quantity": "1",
                "price": "120",
                "prints": "100",
                "clicks": "5",
            }],
        },
        "sales": {
            "date_from": "2026-07-03",
            "date_to": "2026-08-01",
            "items": {
                "MLB123": {
                    "revenue_total": "120",
                    "units_total": "2",
                    "sku": "SKU-123",
                    "title": "Produto teste",
                }
            },
        },
        }
        calls = []

        def fake_fetch(path, params):
            calls.append((path, params.copy()))
            return payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            _, error = app._build_online_dashboard_data(
                client="conta-ativa",
                advertiser_id="123",
                date_from="",
                date_to="",
                requested_period={
                    "dateFrom": "2026-07-03",
                    "dateTo": "2026-08-01",
                },
            )

        self.assertEqual(error, "")
        self.assertTrue(calls)
        self.assertTrue(
            all(
                params.get("date_from") == "2026-07-03"
                and params.get("date_to") == "2026-08-01"
                for _, params in calls
            )
        )

    def test_period_picker_has_opaque_surface_and_stack(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        self.assertIn("z-index:30", source)
        self.assertIn("background:var(--card)", source)
        self.assertNotIn("background:var(--surface)", source)

    def test_dashboard_contains_beta_period_controls(self):
        period = app._resolve_online_period("7", compare="previous", now=NOW)
        self.assertTrue(callable(app._build_online_dashboard_data))
        html = render_dashboard({"meta": {"onlineMode": {"enabled": True, "onlinePeriod": period}}, "onlineBeta": {"enabled": True, "requestedPeriod": period}, "items": []})
        self.assertIn('data-online-period', html)
        self.assertIn("Snapshot utilizado", html)
        self.assertIn("Frequência prevista", html)
        self.assertIn('data-online-period-form', html)
        self.assertIn('id="period-month-field"', html)
        self.assertIn('id="period-custom-fields"', html)
        self.assertIn('Nao comparar', html)
        self.assertIn("Ultimos 7 dias", html)


if __name__ == "__main__":
    unittest.main()
