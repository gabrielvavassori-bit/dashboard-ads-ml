import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app
from gerar_dashboard_ads_ml import render_dashboard


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


class OnlinePeriodTests(unittest.TestCase):
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
                        "user_product_id": "MLBU-7X4",
                        "catalog_product_id": "CAT-7X4",
                        "catalog_listing": True,
                        "sku": "LAZ-7X4",
                        "title": "Condicao A",
                        "cost": 10,
                        "total_amount": 100,
                        "direct_amount": 80,
                        "prints": 1000,
                        "clicks": 20,
                        "units_quantity": 5,
                        "price": 114.90,
                    },
                    {
                        "item_id": "MLB6689184622",
                        "campaign_id": "CAMP-2",
                        "campaign_name": "Campanha secundaria",
                        "user_product_id": "MLBU-7X4",
                        "catalog_product_id": "CAT-7X4",
                        "catalog_listing": True,
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
                "items": {
                    "MLB5399002228": {"revenue_total": 500, "orders_count": 4, "units_total": 5},
                    "MLB6689184622": {"revenue_total": 631.84, "orders_count": 1, "units_total": 8},
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
        self.assertTrue(all(item["userProductId"] == "MLBU-7X4" for item in data["items"]))
        self.assertTrue(all(item["conditionCount"] == 2 for item in data["items"]))
        self.assertTrue(all(item["catalogProductId"] == "CAT-7X4" for item in data["items"]))
        self.assertEqual({item["campaign"] for item in data["items"]}, {"Campanha principal", "Campanha secundaria"})
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

    def test_sales_intelligence_does_not_mask_daily_snapshot_failure_as_empty_base(self):
        latest = {
            "sales": {"items": {"MLB123": {
                "sku": "SKU-123", "units_total": 1, "revenue_total": 50,
            }}},
            "ads": {"items": []},
        }
        user = {"name": "Cliente", "email": "cliente@example.com"}
        link = {"client_id": "cliente", "advertiser_id": "1", "official_store": "Loja", "nickname": ""}

        with patch.object(app, "_sales_intelligence_fetch_latest", return_value=(latest, "")), \
             patch.object(app, "_sales_intelligence_fetch_daily_sales", return_value=([], "worker_timeout")):
            data, message = app._build_sales_intelligence_memory_data(user, link)

        self.assertIsNone(data)
        self.assertIn("snapshots diarios", message)
        self.assertIn("worker_timeout", message)

    def test_sales_intelligence_asset_counts_aggregated_daily_orders(self):
        source = Path(__file__).with_name("assets").joinpath("inteligencia-vendas-marketplace.html").read_text(encoding="utf-8")
        self.assertIn("function orderCountOf(sale)", source)
        self.assertIn("const orders = sumOrderCount(rows);", source)
        self.assertIn("window.__marketplaceAppReady = boot();", source)

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
        "sales": {"items": {
            "MLB123": {
                "revenue_total": "120",
                "units_total": "2",
                "sku": "SKU-123",
                "title": "Produto teste",
            }
        }},
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
