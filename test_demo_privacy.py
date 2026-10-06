"""Regression tests for the transient, presentation-only Dash Ads Demo mode."""
import copy
import os
import unittest
from pathlib import Path

os.environ.setdefault("DASH_DEMO_COOKIE_SECRET", "test-demo-cookie-secret")

import auth
from gerar_dashboard_ads_ml import anonymize_dashboard_data, render_dashboard


def sample_dashboard():
    item = {
        "sku": "LAZ-5X4",
        "code": "MLB5913675930",
        "allCodes": "MLB5913675930, MLB5913675931",
        "title": "Lona Azul Especial 5x4",
        "campaign": "Campanha Lonas Setembro",
        "familyId": "FAM-550",
        "familyName": "Lonas Azul",
        "parentId": "MLBU-991",
        "userProductName": "Lona Azul 5x4",
        "conditionLabel": "Variação Azul",
        "catalogLabel": "CAT-88",
        "thumbnailUrl": "https://http2.mlstatic.com/D_REAL_IMAGE.jpg",
        "orders": 92,
        "units": 101,
        "totalRevenue": 30145.19,
        "adsRevenue": 13734.88,
        "investment": 842.17,
        "tacos": 0.02795,
        "dailySeries": [{"date": "2026-09-02", "revenue": 1280.5, "orders": 5}],
    }
    return {
        "kpis": {"clientName": "Lonas Online", "revenue": 30145.19, "investment": 842.17},
        "meta": {"onlineMode": {"enabled": True, "onlinePeriod": {"dateFrom": "2026-09-01", "dateTo": "2026-09-07"}}},
        "items": [item, copy.deepcopy(item)],
        "skuAds": [copy.deepcopy(item)],
        "campaignAds": [copy.deepcopy(item)],
        "onlineBeta": {
            "enabled": True,
            "client": "lonas-online",
            "advertiserId": "14252670",
            "context": {"nickname": "LONAS_ONLINE", "thumbnail_url": "https://http2.mlstatic.com/raw.jpg"},
            "latest": {"sales": {"items": {"MLB5913675930": {"title": "Lona Azul Especial 5x4"}}}},
        },
    }


class DemoPrivacyTests(unittest.TestCase):
    def test_anonymization_preserves_financial_values_and_original_payload(self):
        original = sample_dashboard()
        before = copy.deepcopy(original)
        demo = anonymize_dashboard_data(original)

        self.assertEqual(original, before)
        self.assertEqual(demo["kpis"]["revenue"], before["kpis"]["revenue"])
        self.assertEqual(demo["items"][0]["totalRevenue"], before["items"][0]["totalRevenue"])
        self.assertEqual(demo["items"][0]["investment"], before["items"][0]["investment"])
        self.assertEqual(demo["items"][0]["dailySeries"], before["items"][0]["dailySeries"])

    def test_aliases_are_deterministic_and_images_never_reach_browser_payload(self):
        demo = anonymize_dashboard_data(sample_dashboard())
        first, repeated = demo["items"]
        self.assertEqual(first["sku"], repeated["sku"])
        self.assertEqual(first["code"], repeated["code"])
        self.assertEqual(first["title"], repeated["title"])
        self.assertEqual(first["thumbnailUrl"], "")
        self.assertEqual(demo["onlineBeta"], {"enabled": False, "demo": True})

        rendered = render_dashboard(demo)
        for forbidden in (
            "Lonas Online", "lonas-online", "LONAS_ONLINE", "LAZ-5X4", "MLB5913675930",
            "Lona Azul Especial", "Campanha Lonas", "D_REAL_IMAGE.jpg",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("MODO DEMO ATIVO", rendered)
        self.assertIn("SKU DEMO 001", rendered)
        self.assertIn("ANUNCIO DEMO 001", rendered)

    def test_signed_demo_cookie_is_short_lived_and_tamper_resistant(self):
        cookie = auth.make_demo_set_cookie(42)
        token = cookie.split(";", 1)[0].split("=", 1)[1]
        self.assertEqual(auth.get_demo_context(token), {"account_id": 42})
        self.assertIsNone(auth.get_demo_context(token + "x"))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Max-Age=28800", cookie)

    def test_demo_mode_has_no_persistent_write_path(self):
        source = Path("app.py").read_text(encoding="utf-8")
        activate = source.split("def _post_admin_demo_activate", 1)[1].split("def _post_admin_demo_deactivate", 1)[0]
        deactivate = source.split("def _post_admin_demo_deactivate", 1)[1].split("def _post_admin_login", 1)[0]
        for forbidden in ("create_session", "set_session", "log_audit", "upsert_", "UPDATE", "INSERT", "DELETE"):
            self.assertNotIn(forbidden, activate)
            self.assertNotIn(forbidden, deactivate)


if __name__ == "__main__":
    unittest.main()
