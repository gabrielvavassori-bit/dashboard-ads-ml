import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app
from gerar_dashboard_ads_ml import aggregate_by_sku, render_dashboard


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


def complete_integrity_contract(client: str, advertiser_id: str, date_from: str, date_to: str) -> dict:
    """Representa o único contrato que pode liberar KPIs online."""
    source = {
        "complete": True,
        "expected_item_days": 1,
        "persisted_item_days": 1,
        "missing_item_days": 0,
        "missing_items": [],
        "errors": [],
        "source_errors": [],
    }
    return {
        "period_cache_hit": True,
        "period_cache_complete": True,
        "integrity_contract": {
            "rule_id": app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID,
            "state": "complete",
            "complete": True,
            "fail_closed": True,
            "governance": {
                "rule_id": app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID,
                "classification": "COMPARTILHADA",
                "status": "D",
                "implementation_status": "NAO_IMPLEMENTADO",
                "active": True,
                "source": "agent_bundle",
                "source_file": "shared_rules.json",
                "consulted_files": ["knowledge/shared_rules.json"],
                "loaded_at": "2026-09-14T12:00:00-03:00",
            },
            "requested_period": {"date_from": date_from, "date_to": date_to, "days": 1},
            "identity": {
                "client_id": client,
                "advertiser_id": advertiser_id,
                "seller_id": "seller-test",
            },
            "universe": {
                "complete": True,
                "ads": {"complete": True, "item_ids": [], "total": 1, "error": ""},
                "sales": {"complete": True, "item_ids": [], "total": 1, "error": ""},
            },
            "ads": dict(source),
            "sales": dict(source),
            "errors": [],
        },
    }


def complete_daily_coverage(date_from: str, date_to: str) -> dict:
    """Recibo explícito necessário para liberar uma série financeira diária."""
    start = datetime.fromisoformat(date_from).date()
    end = datetime.fromisoformat(date_to).date()
    coverage = {}
    while start <= end:
        coverage[start.isoformat()] = {"complete": True}
        start += timedelta(days=1)
    return coverage


def repair_pending_integrity_contract(client: str, advertiser_id: str, date_from: str, date_to: str) -> dict:
    payload = complete_integrity_contract(client, advertiser_id, date_from, date_to)
    contract = payload["integrity_contract"]
    contract["state"] = "repair_pending"
    contract["complete"] = False
    contract["universe"]["complete"] = False
    for source in ("ads", "sales"):
        contract[source]["complete"] = False
        contract[source]["persisted_item_days"] = 0
        contract[source]["missing_item_days"] = 1
        contract[source]["missing_items"] = ["pending"]
        contract["universe"][source]["complete"] = False
    payload["period_cache_hit"] = False
    payload["period_cache_complete"] = False
    return payload


def active_snapshot_completeness_rule() -> dict:
    """Resultado normalizado da consulta central, sem depender da rede no unit test."""
    return {
        "ok": True,
        "rule": {
            "id": app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID,
            "classification": "COMPARTILHADA",
            "active": True,
            "changes_behavior": True,
            "status": "D",
            "implementation_status": "NAO_IMPLEMENTADO",
            "source_file": "shared_rules.json",
        },
        "source_file": "shared_rules.json",
        "loaded_at": "2026-09-14T12:00:00-03:00",
    }


class OnlinePeriodTests(unittest.TestCase):
    def setUp(self):
        self._governance_rule_loader = patch.object(
            app,
            "_load_snapshot_completeness_governance_rule",
            return_value=active_snapshot_completeness_rule(),
        )
        self._governance_rule_loader.start()

    def tearDown(self):
        self._governance_rule_loader.stop()

    def test_product_daily_chart_does_not_turn_missing_series_into_zeroes(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        daily_series = source.split("function dailySeriesFor(item)", 1)[1].split(
            "function chartDateLabel", 1
        )[0]

        self.assertLess(
            daily_series.index("if (!rows.length) return rows;"),
            daily_series.index("const period ="),
        )

    def test_consolidated_daily_series_deduplicates_repeated_mlb_rows(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        daily_series = source.split("function dailySeriesFor(item)", 1)[1].split(
            "function chartDateLabel", 1
        )[0]

        self.assertIn("const sourcesByCode = new Map();", daily_series)
        self.assertIn("const key = code ? `code:${{code}}` : `row:${{index}}`;", daily_series)

    def test_sku_view_exposes_consolidated_reading(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")

        self.assertIn("scope:'sku'", source)
        self.assertIn("aggregateDetailRows(item, 'SKU')", source)
        self.assertIn("SKU consolidado", source)

    def test_only_product_hierarchies_start_collapsed(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        period = {"dateFrom": "2026-09-01", "dateTo": "2026-09-07"}
        html = render_dashboard({
            "meta": {"onlineMode": {"enabled": True, "onlinePeriod": period}},
            "onlineBeta": {"enabled": True, "requestedPeriod": period},
            "items": [],
        })

        self.assertNotIn('<details class="card dashboard-section', html)
        self.assertNotIn('<summary>Indicadores da conta</summary>', html)
        self.assertNotIn('<summary>Desempenho diário da conta</summary>', html)
        self.assertNotIn('<summary>Alertas principais</summary>', html)
        self.assertNotIn('<summary>Leitura auxiliar de CTR e CVR</summary>', html)
        self.assertNotIn('<summary>Curva ABC de vendas</summary>', html)
        self.assertNotIn('<summary>Online Beta</summary>', html)
        self.assertNotIn('<summary>Análise operacional dos produtos</summary>', html)
        self.assertIn("const familyExpanded = new Set();", source)
        self.assertIn("const skuExpanded = new Set();", source)
        self.assertIn("const expanded = familyExpanded.has(key);", source)
        self.assertIn("const expanded = skuExpanded.has(key);", source)
        self.assertIn("data-hierarchy-kind=\"${{safe(kind)}}\"", source)

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

    def test_missing_thumbnail_does_not_refresh_a_ready_financial_snapshot(self):
        date_from = date_to = "2026-08-10"
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", date_from, date_to),
            "ok": True,
            "latest": {
                "date_from": date_from,
                "date_to": date_to,
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": date_from,
                "date_to": date_to,
                "items": [{
                    "item_id": "MLB123",
                    "cost": 10,
                    "total_amount": 100,
                    "direct_amount": 80,
                    "prints": 100,
                    "clicks": 10,
                    "units_quantity": 1,
                }],
            },
            "campaigns": {"campaigns": []},
            "sales": {
                "date_from": date_from,
                "date_to": date_to,
                "items": {"MLB123": {"revenue_total": 120, "units_total": 2}},
            },
        }
        calls = []

        def fetch(path, params):
            calls.append((path, params))
            if path.endswith("online-cache-refresh"):
                self.fail("Miniatura ausente nao pode acionar refresh financeiro")
            return payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, error = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", date_from, date_to,
                {"dateFrom": date_from, "dateTo": date_to},
            )

        self.assertEqual(error, "")
        self.assertIsNotNone(data)
        self.assertEqual(calls[0][0], "/internal/dash-ads/operational-cache")
        self.assertNotIn(
            "/internal/dash-ads/online-cache-refresh",
            [path for path, _params in calls],
        )

    def test_daily_snapshots_expose_partial_dates_to_the_dashboard(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value={
            "ok": True,
            "rows": [{"item_id": "MLB1", "snapshot_date": "2026-08-10"}],
            "coverage_days": {
                "2026-08-10": {"complete": False},
                "2026-08-11": {"complete": True},
            },
        }):
            rows, coverage_days, error = app._sales_intelligence_fetch_daily_sales(
                "cliente", "2026-08-10", "2026-08-11"
            )

        self.assertEqual(error, "")
        self.assertEqual(rows[0]["item_id"], "MLB1")
        self.assertEqual(app._daily_partial_snapshot_dates(coverage_days), {"2026-08-10"})

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
        self.assertIn("aggregateDetailItem(group.children, {{scope:'mlbu'", source)
        self.assertIn("aggregateDetailItem(group.children, {{scope:'family'", source)
        self.assertIn('data-hierarchy-toggle=', source)
        self.assertIn("data-hierarchy-kind=\"${{safe(kind)}}\"", source)
        self.assertIn("Ver leitura ${{article}} ${{safe(label)}}", source)
        self.assertIn('id="detailModal"', source)
        self.assertIn("['performance', 'Desempenho']", source)
        self.assertIn("['diagnosis', 'Diagnóstico']", source)
        self.assertIn("['promotions', 'Promoções']", source)
        self.assertIn("['advertising', 'Publicidade']", source)
        self.assertIn('grid-template-rows:auto auto minmax(0,1fr)', source)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', source)
        self.assertIn('overflow-x:hidden; overflow-y:auto', source)
        self.assertIn('.detail-modal-tabs button {{ width:100%; min-width:0; }}', source)
        self.assertIn('.detail-modal-body .child-table thead th {{ position:static;', source)
        self.assertIn('modalBody.scrollTop = 0;', source)
        self.assertNotIn('const detailExpanded = new Set()', source)
        self.assertIn("const expanded = mlbuExpanded.has(key)", source)
        self.assertIn("const expanded = familyExpanded.has(key)", source)
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
        online_builder = Path(__file__).with_name("app.py").read_text(encoding="utf-8").split(
            "def _build_online_dashboard_data", 1
        )[1].split("def _build_online_beta_payload", 1)[0]
        self.assertNotIn('"refresh_metadata": "1"', online_builder)

    def test_campaign_reading_has_search_and_two_way_sorting_for_its_rows(self):
        source = Path(__file__).with_name("gerar_dashboard_ads_ml.py").read_text(encoding="utf-8")
        campaign_children = source.split("function campaignChildren(item)", 1)[1].split(
            "function listingTypeLabel", 1
        )[0]

        self.assertIn('data-campaign-child-search', campaign_children)
        self.assertIn('data-campaign-child-sort', campaign_children)
        self.assertIn("function campaignChildrenForDisplay(children)", campaign_children)
        self.assertIn("campaignChildSort.direction === 'desc' ? bv - av : av - bv", campaign_children)
        self.assertIn("campaignChildSort.direction === 'desc' ? -comparison : comparison", campaign_children)
        self.assertIn("updatedSearch.setSelectionRange", source)

    def test_online_builder_keeps_campaign_condition_and_catalog_links_separate(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-04", "2026-08-10"),
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-08-04", "2026-08-10"),
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
                        "secure_thumbnail": "https://http2.mlstatic.com/condition-b.jpg",
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
        self.assertEqual(condition_b["thumbnailUrl"], "https://http2.mlstatic.com/condition-b.jpg")

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
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-07", "2026-08-13"),
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
                }, {
                    "item_id": "MLB9999999999",
                    "campaign_id": "CAMP-2",
                    "sku": "CONTA-2",
                    "title": "Segundo produto",
                    "cost": 5,
                    "total_amount": 30,
                    "direct_amount": 20,
                    "prints": 200,
                    "clicks": 10,
                    "units_quantity": 1,
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
                }, "MLB9999999999": {
                    "revenue_total": 100,
                    "orders_count": 2,
                    "units_total": 2,
                    "last_sale_date": "2026-08-11T13:00:00-03:00",
                    "last_price": 50,
                }},
            },
        }
        daily_payload = {
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-08-07", "2026-08-13"),
            "rows": [
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-11", "orders_count": 1, "units_total": 1, "revenue_total": 29.90, "last_price": 29.90},
                {"item_id": "MLB9999999999", "snapshot_date": "2026-08-11", "orders_count": 2, "units_total": 2, "revenue_total": 100, "last_price": 50},
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-12", "orders_count": 0, "units_total": 0, "revenue_total": 0},
                {"item_id": "MLB5364060738", "snapshot_date": "2026-08-13", "orders_count": 0, "units_total": 0, "revenue_total": 0},
            ],
        }
        daily_ads_payload = {
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-08-07", "2026-08-13"),
            "rows": [{
                "item_id": "MLB5364060738", "snapshot_date": "2026-08-11",
                "campaign_id": "CAMP-1", "cost": 10, "total_amount": 50,
                "direct_amount": 40, "indirect_amount": 10,
                "prints": 100, "clicks": 5, "units_quantity": 2,
            }, {
                "item_id": "MLB9999999999", "snapshot_date": "2026-08-11",
                "campaign_id": "CAMP-2", "cost": 5, "total_amount": 30,
                "direct_amount": 20, "indirect_amount": 10,
                "prints": 200, "clicks": 10, "units_quantity": 1,
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
        account_daily = data["accountDailySeries"]
        self.assertEqual([row["date"] for row in account_daily], ["2026-08-11", "2026-08-12", "2026-08-13"])
        self.assertEqual(account_daily[0]["orders"], 3)
        self.assertEqual(account_daily[0]["units"], 3)
        self.assertEqual(account_daily[0]["revenue"], 129.90)
        self.assertEqual(account_daily[0]["adsRevenue"], 80)
        self.assertEqual(account_daily[0]["investment"], 15)
        self.assertAlmostEqual(account_daily[0]["price"], 129.90 / 3)
        self.assertAlmostEqual(account_daily[0]["roas"], 80 / 15)
        self.assertAlmostEqual(account_daily[0]["tacos"], 15 / 149.90)

        html = render_dashboard(data)
        self.assertIn('data-account-daily-chart', html)
        self.assertIn("<h3>Desempenho diário da conta</h3>", html)
        self.assertNotIn("<summary>Desempenho diário da conta</summary>", html)
        self.assertLess(html.index('id="kpis"'), html.index('data-account-daily-chart'))
        self.assertLess(html.index('data-account-daily-chart'), html.index('aria-label="Visoes do dashboard"'))
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
        self.assertIn("BETA TRANSACIONAL COM CONFIRMACAO", html)
        self.assertIn("Promocoes do Mercado Livre", html)
        self.assertIn("Gerar previa", html)
        self.assertIn("Confirmar e aplicar no Mercado Livre", html)
        self.assertIn("Aplicar esta promocao real no anuncio", html)
        self.assertIn("Desconto total", html)
        self.assertIn("Parte do vendedor", html)
        self.assertIn("Parte Mercado Livre", html)
        self.assertIn("Rebate nas tarifas ML", html)
        self.assertIn("discount_meli_boost_amount", html)

    def test_account_daily_chart_does_not_invent_missing_snapshot_dates(self):
        latest_payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-07", "2026-08-13"),
            "ok": True,
            "latest": {
                "date_from": "2026-08-07", "date_to": "2026-08-13",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-07", "date_to": "2026-08-13",
                "items": [{"item_id": "MLB1", "sku": "SKU-1", "cost": 10}],
            },
            "campaigns": {"campaigns": []},
            "sales": {
                "date_from": "2026-08-07", "date_to": "2026-08-13",
                "items": {"MLB1": {"orders_count": 1, "units_total": 1, "revenue_total": 50}},
            },
        }

        def fetch(path, params=None):
            if path in ("/internal/dash-ads/sales-daily", "/internal/dash-ads/ads-daily"):
                return {
                    "ok": True,
                    "rows": [],
                    "coverage_days": complete_daily_coverage("2026-08-07", "2026-08-13"),
                }
            return latest_payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, error = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-07", "2026-08-13",
                {"dateFrom": "2026-08-07", "dateTo": "2026-08-13"},
            )

        self.assertEqual(error, "")
        self.assertEqual(data["accountDailySeries"], [])
        html = render_dashboard(data)
        self.assertIn("A série diária da conta ainda não está disponível", html)
        account_activation = html.split("function activateAccountDailyChart()", 1)[1].split(
            "function dailyChartBlock", 1
        )[0]
        self.assertNotIn("dailySeriesFor", account_activation)

    def test_governance_summary_reads_authenticated_agent_bundle(self):
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

        agent_payload = {
            "ok": True,
            "loaded_at": bundle["published_at"],
            "bundle_sha256": "abc123",
            "files": bundle["files"],
            "registry": bundle["files"]["shared_rules.json"],
        }
        with patch.object(app, "_fetch_dash_ads_json", return_value=agent_payload) as fetch_agent:
            payload, status = app._fetch_governance_summary()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["central_rules_count"], 2)
        self.assertEqual(payload["shared_human_decisions_count"], 1)
        self.assertEqual(payload["project_decisions"][0]["id"], "UNC-1")
        self.assertEqual(fetch_agent.call_args.args[0], "/internal/dash-ads/governance-rule")

    def test_governance_summary_fails_closed_when_agent_bundle_is_unavailable(self):
        with patch.object(app, "_fetch_dash_ads_json", return_value={"ok": False, "error": "unavailable"}):
            payload, status = app._fetch_governance_summary()
        self.assertEqual(status, 502)
        self.assertFalse(payload["ok"])

    def test_snapshot_rule_loader_reads_authenticated_agent_bundle(self):
        agent_payload = {
            "ok": True,
            "loaded_at": "2026-09-15T10:00:00-03:00",
            "bundle_sha256": "a" * 64,
            "registry": {
                "rules": [{
                    "id": app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID,
                    "classification": "COMPARTILHADA",
                    "active": True,
                    "changes_behavior": True,
                    "status": "D",
                    "implementation_status": "NAO_IMPLEMENTADO",
                }],
            },
        }

        self._governance_rule_loader.stop()
        try:
            empty_cache = {"key": None, "expires_at": 0.0, "result": None}
            with patch.object(app, "_governance_rule_cache", empty_cache), \
                 patch.object(app, "_fetch_dash_ads_json", return_value=agent_payload) as fetch:
                result = app._load_snapshot_completeness_governance_rule()
        finally:
            self._governance_rule_loader.start()

        self.assertTrue(result["ok"])
        self.assertEqual(result["rule"]["id"], app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID)
        self.assertEqual(result["rule"]["bundle_sha256"], "a" * 64)
        self.assertEqual(fetch.call_args.args[0], "/internal/dash-ads/governance-rule")

    def test_snapshot_rule_loader_uses_agent_bundle_once_within_ttl(self):
        bundle = {
            "published_at": "2026-09-14T12:00:00-03:00",
            "files": {
                "shared_rules.json": {
                    "rules": [{
                        "id": app.DASH_ADS_SNAPSHOT_COMPLETENESS_RULE_ID,
                        "classification": "COMPARTILHADA",
                        "active": True,
                        "changes_behavior": True,
                        "status": "D",
                        "implementation_status": "NAO_IMPLEMENTADO",
                    }],
                },
            },
        }

        agent_payload = {
            "ok": True,
            "loaded_at": bundle["published_at"],
            "bundle_sha256": "b" * 64,
            "registry": bundle["files"]["shared_rules.json"],
        }
        self._governance_rule_loader.stop()
        try:
            empty_cache = {"key": None, "expires_at": 0.0, "result": None}
            with patch.object(app, "_governance_rule_cache", empty_cache), \
                 patch.object(app, "_fetch_dash_ads_json", return_value=agent_payload) as fetch_agent:
                first = app._load_snapshot_completeness_governance_rule()
                second = app._load_snapshot_completeness_governance_rule()
        finally:
            self._governance_rule_loader.start()

        self.assertTrue(first["ok"])
        self.assertEqual(first["rule"]["status"], "D")
        self.assertEqual(first["rule"]["source_file"], "shared_rules.json")
        self.assertEqual(second, first)
        self.assertEqual(fetch_agent.call_count, 1)

    def test_online_integrity_blocks_when_central_rule_cannot_be_consulted(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-11", "2026-08-17"),
            "ok": True,
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": []},
            "sales": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": {}},
        }
        with patch.object(
            app,
            "_load_snapshot_completeness_governance_rule",
            return_value={"ok": False, "reason": "governance_read_api_key_not_configured"},
        ):
            integrity = app._online_cache_integrity_state(
                payload, "conta-ativa", "adv-1", "2026-08-11", "2026-08-17"
            )

        self.assertFalse(integrity["ready"])
        self.assertFalse(integrity["pending"])
        self.assertIn("consulta da regra central falhou", integrity["message"])

    def test_online_integrity_blocks_when_agent_bundle_hash_diverges(self):
        date_from, date_to = "2026-08-11", "2026-08-17"
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", date_from, date_to),
            "ok": True,
            "latest": {"date_from": date_from, "date_to": date_to, "sales": {"complete": True}},
            "ads": {"date_from": date_from, "date_to": date_to, "items": []},
            "sales": {"date_from": date_from, "date_to": date_to, "items": {}},
        }
        payload["integrity_contract"]["governance"]["bundle_sha256"] = "a" * 64
        central = active_snapshot_completeness_rule()
        central["rule"]["bundle_sha256"] = "b" * 64
        with patch.object(app, "_load_snapshot_completeness_governance_rule", return_value=central):
            integrity = app._online_cache_integrity_state(
                payload, "conta-ativa", "adv-1", date_from, date_to
            )

        self.assertFalse(integrity["ready"])
        self.assertIn("recibo da regra central não foi comprovado", integrity["message"])

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
            **complete_integrity_contract("cliente-teste", "adv-1", "2026-07-24", "2026-07-30"),
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-07-24", "2026-07-30"),
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
            **complete_integrity_contract("conta-ativa", "123", "2026-07-24", "2026-07-30"),
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
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("janela de cache diverge", message)
        self.assertEqual(
            [path for path, _ in calls],
            ["/internal/dash-ads/operational-cache"],
        )

    def test_online_builder_rejects_ads_from_a_different_period(self):
        mixed_payload = {
            **complete_integrity_contract("varietyshop1", "adv-1", "2026-08-11", "2026-08-17"),
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
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("janela de Ads diverge", message)

    def test_online_builder_blocks_partial_ads_coverage_before_financial_rendering(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-11", "2026-08-17"),
            "ok": True,
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "complete": False,
                "coverage": {"complete": False},
                "items": [{"item_id": "MLB1", "cost": 10, "total_amount": 100}],
            },
            "sales": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": {"MLB1": {"revenue_total": 120, "units_total": 1}},
            },
        }
        contract = payload["integrity_contract"]
        contract["ads"].update({
            "complete": False,
            "persisted_item_days": 0,
            "missing_item_days": 1,
            "missing_items": ["MLB1"],
        })
        contract["universe"]["ads"]["complete"] = False
        contract["universe"]["complete"] = False

        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, message = app._build_online_dashboard_data(
                "conta-ativa",
                "adv-1",
                "2026-08-11",
                "2026-08-17",
                {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("cobertura de Ads não foi comprovada", message)

    def test_online_builder_blocks_when_daily_sales_coverage_turns_partial(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-11", "2026-08-17"),
            "ok": True,
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": [{
                    "item_id": "MLB1", "cost": 10, "total_amount": 100,
                    "thumbnail_url": "https://http2.mlstatic.com/image.jpg",
                }],
            },
            "sales": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": {"MLB1": {"revenue_total": 120, "units_total": 1}},
            },
        }

        def fetch(path, _params=None):
            if path.endswith("sales-daily"):
                return {
                    "ok": True,
                    "rows": [{"item_id": "MLB1", "snapshot_date": "2026-08-12", "revenue_total": 120}],
                    "coverage_days": {
                        **complete_daily_coverage("2026-08-11", "2026-08-17"),
                        "2026-08-12": {"complete": False},
                    },
                }
            if path.endswith("ads-daily"):
                return {
                    "ok": True,
                    "rows": [],
                    "coverage_days": complete_daily_coverage("2026-08-11", "2026-08-17"),
                }
            return payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, message = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-11", "2026-08-17",
                {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("cobertura diária de vendas não foi comprovada", message)

    def test_online_builder_blocks_daily_ads_without_explicit_complete_coverage(self):
        date_from = date_to = "2026-08-11"
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", date_from, date_to),
            "ok": True,
            "latest": {
                "date_from": date_from,
                "date_to": date_to,
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": date_from,
                "date_to": date_to,
                "items": [{
                    "item_id": "MLB1",
                    "thumbnail_url": "https://http2.mlstatic.com/image.jpg",
                    "cost": 10,
                    "total_amount": 100,
                }],
            },
            "sales": {
                "date_from": date_from,
                "date_to": date_to,
                "items": {"MLB1": {"revenue_total": 120, "units_total": 1}},
            },
        }
        daily_sales = {
            "ok": True,
            "rows": [],
            "coverage_days": complete_daily_coverage(date_from, date_to),
        }
        cases = {
            "ausente": (
                {"ok": True, "rows": [{"item_id": "MLB1", "snapshot_date": date_from, "cost": 10, "total_amount": 100}]},
                None,
            ),
            "none": (
                {"ok": True, "rows": [{"item_id": "MLB1", "snapshot_date": date_from, "cost": 10, "total_amount": 100}], "coverage_days": {date_from: {"complete": None}}},
                None,
            ),
            "false": (
                {"ok": True, "rows": [], "coverage_days": {date_from: {"complete": False}}},
                "cobertura diária de Ads não foi comprovada",
            ),
            "erro": (
                {
                    "ok": True,
                    "rows": [],
                    "coverage_days": complete_daily_coverage(date_from, date_to),
                    "error": "upstream_timeout",
                },
                "fonte diária de Ads reportou erro",
            ),
        }

        for label, (daily_ads, expected_reason) in cases.items():
            with self.subTest(label=label):
                def fetch(path, _params=None):
                    if path.endswith("sales-daily"):
                        return daily_sales
                    if path.endswith("ads-daily"):
                        return daily_ads
                    return payload

                with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
                    data, message = app._build_online_dashboard_data(
                        "conta-ativa", "adv-1", date_from, date_to,
                        {"dateFrom": date_from, "dateTo": date_to},
                    )

                if expected_reason is None:
                    self.assertIsNotNone(data)
                    self.assertEqual(message, "")
                else:
                    self.assertIsNone(data)
                    self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
                    self.assertIn(expected_reason, message)

    def test_online_builder_blocks_inconsistent_ads_without_diagnostic_row_replacement(self):
        date_from = date_to = "2026-08-11"
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", date_from, date_to),
            "ok": True,
            "latest": {
                "date_from": date_from,
                "date_to": date_to,
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": date_from,
                "date_to": date_to,
                "items": [{
                    "item_id": "MLB1",
                    "thumbnail_url": "https://http2.mlstatic.com/image.jpg",
                    "cost": 10,
                    "total_amount": 200,
                }],
            },
            "sales": {
                "date_from": date_from,
                "date_to": date_to,
                "items": {"MLB1": {"revenue_total": 120, "units_total": 1}},
            },
        }
        calls = []

        def fetch(path, _params=None):
            calls.append(path)
            if path.endswith("ads-api-reconciliacao"):
                self.fail("A reconciliação diagnóstica não pode substituir linhas financeiras")
            return payload

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, message = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", date_from, date_to,
                {"dateFrom": date_from, "dateTo": date_to},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("receita atribuída por Ads supera o faturamento bruto", message)
        self.assertEqual(calls, ["/internal/dash-ads/operational-cache"])

    def test_online_builder_accepts_agent_source_errors_alias_for_complete_coverage(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-11", "2026-08-17"),
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-08-11", "2026-08-17"),
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": [{"item_id": "MLB1", "cost": 10, "total_amount": 100}],
            },
            "sales": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "items": {"MLB1": {"revenue_total": 120, "units_total": 1}},
            },
        }
        for source in ("ads", "sales"):
            payload["integrity_contract"][source].pop("errors")

        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, message = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-11", "2026-08-17",
                {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"},
            )

        self.assertEqual(message, "")
        self.assertIsNotNone(data)

    def test_online_builder_blocks_when_agent_governance_receipt_diverges(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "adv-1", "2026-08-11", "2026-08-17"),
            "ok": True,
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": True},
            },
            "ads": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": []},
            "sales": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": {}},
        }
        payload["integrity_contract"]["governance"]["status"] = "C"

        with patch.object(app, "_fetch_dash_ads_json", return_value=payload):
            data, message = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-11", "2026-08-17",
                {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("recibo da regra central não foi comprovado", message)

    def test_offline_online_beta_skips_reconciliation_when_cache_integrity_is_untrusted(self):
        calls = []
        untrusted = {
            "ok": True,
            "status": "failed",
            "latest": {
                "date_from": "2026-08-11",
                "date_to": "2026-08-17",
                "sales": {"complete": False},
            },
            "ads": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": []},
            "sales": {"date_from": "2026-08-11", "date_to": "2026-08-17", "items": {}},
        }

        def fake_fetch(path, _params):
            calls.append(path)
            if path.endswith("ml-context"):
                return {"ok": True, "advertiser_id": "adv-1"}
            if path.endswith("online-cache-latest"):
                return untrusted
            self.fail(f"A rota {path} não pode ser chamada sem recibo de integridade completo")

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            result = app._build_online_beta_payload(
                {"meta": {"period": {"dateFrom": "2026-08-11", "dateTo": "2026-08-17"}}},
                "conta-ativa",
                "adv-1",
            )

        self.assertFalse(result["enabled"])
        self.assertTrue(result["integrityBlocked"])
        self.assertIn("Dados financeiros não foram exibidos", result["integrityMessage"])
        self.assertNotIn("ads-api-reconciliacao", calls)

    def test_online_builder_reports_pending_when_no_snapshot_is_available(self):
        stale_payload = {
            **repair_pending_integrity_contract("conta-ativa", "", "2026-07-24", "2026-07-30"),
            "ok": True,
            "period_cache_hit": False,
            "period_cache_complete": False,
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
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("reparação", message)

    def test_online_builder_never_renders_a_completed_snapshot_from_another_period(self):
        pending = {
            **repair_pending_integrity_contract("conta-ativa", "adv-1", "2026-08-05", "2026-09-03"),
            "ok": True,
            "latest": {},
            "ads": {},
            "sales": {},
        }
        calls = []

        def fetch(path, params=None):
            calls.append(path)
            if path.endswith("online-cache-refresh"):
                return {"ok": True, "status": "running"}
            return pending

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fetch):
            data, message = app._build_online_dashboard_data(
                "conta-ativa", "adv-1", "2026-08-05", "2026-09-03",
                {"dateFrom": "2026-08-05", "dateTo": "2026-09-03"},
            )

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("reparação", message)
        self.assertNotIn("fallback", " ".join(calls))

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

    def test_sales_intelligence_exposes_never_sold_listing_with_partial_coverage(self):
        latest = {
            "period_cache_complete": True,
            "sales": {"complete": True, "items": {}},
            "ads": {"items": [{
                "item_id": "MLB-NUNCA", "status": "active", "sku": "SKU-NUNCA",
                "title": "Anuncio sem venda", "date_created": "2024-01-10T12:00:00Z",
            }]},
        }
        user = {"name": "Cliente", "email": "cliente@example.com"}
        link = {"client_id": "cliente", "advertiser_id": "1", "official_store": "Loja", "nickname": ""}

        with patch.object(app, "_sales_intelligence_fetch_latest", return_value=(latest, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], "")):
            data, message = app._build_sales_intelligence_memory_data(user, link)

        self.assertEqual(message, "")
        self.assertEqual(data["neverSoldListings"][0]["mlb"], "MLB-NUNCA")
        self.assertEqual(data["neverSoldListings"][0]["classification"], "partial")

    def test_sales_intelligence_blocks_daily_partial_coverage_before_recommendations(self):
        latest = {
            "latest": {"date_from": "2026-08-11", "date_to": "2026-08-17"},
            "sales": {"complete": True, "items": {"MLB1": {"revenue_total": 120, "units_total": 1}}},
            "ads": {"items": [{"item_id": "MLB1", "cost": 10, "total_amount": 100}]},
        }
        user = {"name": "Cliente", "email": "cliente@example.com"}
        link = {"client_id": "cliente", "advertiser_id": "1", "official_store": "Loja", "nickname": ""}
        daily_rows = [{"item_id": "MLB1", "snapshot_date": "2026-08-12", "revenue_total": 120}]
        coverage_days = {"2026-08-12": {"complete": False}}

        with patch.object(app, "_sales_intelligence_fetch_latest", return_value=(latest, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=(daily_rows, coverage_days, "")):
            data, message = app._build_sales_intelligence_memory_data(user, link)

        self.assertIsNone(data)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("snapshots diários reportou cobertura parcial", message)

    def test_never_sold_listing_requires_active_status_and_creation_coverage(self):
        rows = app._sales_intelligence_collect_never_sold_listings({
            "sales": {"items": {}},
            "ads": {"items": [
                {"item_id": "MLB-CONFIRMA", "status": "active", "date_created": "2026-07-10"},
                {"item_id": "MLB-INATIVO", "status": "paused", "date_created": "2026-07-10"},
            ]},
        }, "2026-06-01", True)

        self.assertEqual([row["mlb"] for row in rows], ["MLB-CONFIRMA"])
        self.assertEqual(rows[0]["classification"], "confirmed")

    def test_sales_intelligence_asset_separates_never_sold_from_recent_no_sales(self):
        source = Path(__file__).with_name("assets").joinpath("inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        self.assertIn('data-view="never-sold"', source)
        self.assertIn("function renderNeverSold()", source)
        self.assertIn("neverSoldListings", source)
        self.assertIn("Cobertura insuficiente", source)

    def test_sales_intelligence_reports_pending_while_hourly_refresh_runs(self):
        stale_payload = {
            **repair_pending_integrity_contract("conta-ativa", "adv-1", "2026-04-30", "2026-08-26"),
            "ok": True,
            "period_cache_hit": False,
            "status": {"status": "running"},
            "latest": {
                "date_from": "2026-04-30",
                "date_to": "2026-08-26",
            },
            "ads": {
                "date_from": "2026-04-30",
                "date_to": "2026-08-26",
                "items": [],
            },
            "sales": {
                "date_from": "2026-04-30",
                "date_to": "2026-08-26",
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
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args, (
            "/internal/dash-ads/online-cache-latest",
            {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-28", "date_to": "2026-09-03"},
        ))
        self.assertEqual(fetch.call_args_list[-1].args, (
            "/internal/dash-ads/online-cache-refresh",
            {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-28", "date_to": "2026-09-03"},
        ))

    def test_sales_intelligence_blocks_exact_partial_snapshot_while_backfill_runs(self):
        partial_payload = {
            **repair_pending_integrity_contract("conta-ativa", "adv-1", "2026-08-28", "2026-09-03"),
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

        self.assertIsNone(payload)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_PENDING_PREFIX))
        self.assertEqual(fetch.call_count, 2)

    def test_sales_intelligence_never_opens_another_complete_window_while_requested_range_repairs(self):
        requested = {"client": "conta-ativa", "advertiser_id": "adv-1", "date_from": "2026-08-05", "date_to": "2026-09-03"}
        pending = {
            **repair_pending_integrity_contract("conta-ativa", "adv-1", "2026-08-05", "2026-09-03"),
            "ok": True,
            "latest": {},
            "ads": {},
            "sales": {},
        }

        def fake_fetch(path, params):
            if path.endswith("online-cache-refresh"):
                return {"ok": True, "status": "running"}
            return pending

        with patch.object(app, "_fetch_dash_ads_json", side_effect=fake_fetch):
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa", "adv-1", requested["date_from"], requested["date_to"]
            )

        self.assertIsNone(payload)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_PENDING_PREFIX))

    def test_sales_intelligence_does_not_retry_after_terminal_repair_failure(self):
        failed = {
            **repair_pending_integrity_contract("conta-ativa", "adv-1", "2026-08-05", "2026-09-03"),
            "ok": True,
            "status": "failed",
            "latest": {"date_from": "2026-08-05", "date_to": "2026-09-03"},
            "ads": {"date_from": "2026-08-05", "date_to": "2026-09-03", "items": []},
            "sales": {"date_from": "2026-08-05", "date_to": "2026-09-03", "items": {}},
        }
        with patch.object(app, "_fetch_dash_ads_json", return_value=failed) as fetch:
            payload, message = app._sales_intelligence_fetch_latest(
                "conta-ativa", "adv-1", "2026-08-05", "2026-09-03"
            )

        self.assertIsNone(payload)
        self.assertTrue(message.startswith(app.ONLINE_CACHE_INTEGRITY_PREFIX))
        self.assertIn("Estado da reparação: repair_pending", message)
        self.assertEqual(fetch.call_count, 1)

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
        self.assertIn("shipping_seller_debit", mapper)
        self.assertIn("shippingNetAlreadyAllocated", mapper)
        self.assertIn("buyerPriceIncrease: installmentEquivalent", mapper)
        self.assertIn("installmentFee: -installmentEquivalent", mapper)
        self.assertIn("commissionRate", mapper)
        self.assertIn("categoryPath", mapper)
        self.assertIn("shippingSubsidy", mapper)
        self.assertNotIn("shippingSubsidy", financial_base)
        self.assertIn("+ Number(sale?.shippingRevenue || 0)", financial_base)
        self.assertNotIn("shippingNetAlreadyAllocated ? 0", financial_base)
        self.assertIn("Pacote/carrinho", detail)
        self.assertIn("Venda/item", detail)
        self.assertIn("Comissão %", detail)
        self.assertIn("Subsídio/benefício", detail)

    def test_online_builder_uses_requested_period_when_explicit_dates_are_empty(self):
        payload = {
            **complete_integrity_contract("conta-ativa", "123", "2026-07-03", "2026-08-01"),
            "ok": True,
            "coverage_days": complete_daily_coverage("2026-07-03", "2026-08-01"),
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
