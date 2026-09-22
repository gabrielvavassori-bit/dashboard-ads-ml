import ast
import json
import pathlib
import unittest

from gerar_dashboard_ads_ml import _compact_dashboard_transport, render_dashboard


class OnlineMemoryGuardTests(unittest.TestCase):
    def test_transport_omits_raw_snapshot_and_derivable_item_lists(self):
        item = {
            "code": "MLB1",
            "sku": "SKU-1",
            "investment": 10,
            "adsRevenue": 0,
            "totalRevenue": 20,
            "units": 1,
            "tacos": 0.5,
        }
        latest = {
            "latest": {"updated_at": "2026-09-22T10:00:00-03:00"},
            "ads": {"items": [item], "items_total": 1},
            "sales": {"items": {"MLB1": {"revenue_total": 20}}, "items_cached": 1},
            "daily_ads": [{"item_id": "MLB1", "date": "2026-09-21"}],
        }
        data = {
            "items": [item],
            "decisionItems": [item],
            "adsNoSales": [item],
            "highTacos": [item],
            "salesNoAds": [],
            "adsByProduct": [item],
            "finishedNoSku": [],
            "onlineBeta": {"enabled": True, "latest": latest},
        }

        compact = _compact_dashboard_transport(data)

        self.assertIn("latest", data["onlineBeta"])
        self.assertNotIn("latest", compact["onlineBeta"])
        self.assertEqual(compact["onlineBeta"]["cacheSummary"], {
            "updatedAt": "2026-09-22T10:00:00-03:00",
            "adsItems": 1,
            "salesItems": 1,
        })
        for key in ("decisionItems", "adsNoSales", "highTacos", "salesNoAds", "adsByProduct", "finishedNoSku"):
            self.assertNotIn(key, compact)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(data)) * 0.5)

    def test_browser_rebuilds_only_derivable_views(self):
        html = render_dashboard({
            "kpis": {"clientName": "Teste"},
            "meta": {},
            "items": [{"code": "MLB1", "sku": "SKU-1"}],
            "onlineBeta": {"enabled": False},
        })

        self.assertIn("DATA.decisionItems ??=", html)
        self.assertIn("DATA.adsByProduct ??= DATA.decisionItems", html)
        self.assertIn("const cacheSummary = beta.cacheSummary", html)

    def test_online_semaphore_covers_render_and_send(self):
        source = pathlib.Path(__file__).with_name("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        guarded_calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            if not any(isinstance(item.context_expr, ast.Name) and item.context_expr.id == "_online_dashboard_semaphore" for item in node.items):
                continue
            guarded_calls.extend(
                child.func.id
                for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            )
        self.assertIn("_build_online_dashboard_data", guarded_calls)
        self.assertIn("render_dashboard", guarded_calls)
        self.assertIn("_send_html", guarded_calls)
        self.assertIn('os.environ.get("MAX_PARALLEL_ONLINE", "1")', source)


if __name__ == "__main__":
    unittest.main()
