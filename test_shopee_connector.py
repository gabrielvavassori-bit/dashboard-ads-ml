import os
import pathlib
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

import db
import shopee_api


class ShopeeConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        db.DB_PATH = pathlib.Path(self.tempdir.name) / "shopee-test.db"
        db.init_db()
        self.user_id = db.upsert_manual_user("pilot@example.com", "Pilot")

    def tearDown(self):
        db.DB_PATH = self.original_path
        self.tempdir.cleanup()

    def test_state_is_single_use(self):
        db.save_shopee_link_state("state-1", self.user_id)
        first = db.consume_shopee_link_state("state-1")
        self.assertIsNotNone(first)
        self.assertEqual(self.user_id, first["user_id"])
        self.assertIsNone(db.consume_shopee_link_state("state-1"))

    def test_account_listing_never_selects_tokens(self):
        db.upsert_shopee_account(self.user_id, "123", "encrypted-access", "encrypted-refresh")
        row = db.list_active_shopee_accounts_for_user(self.user_id)[0]
        self.assertEqual("123", row["shop_id"])
        self.assertNotIn("access_token_encrypted", row.keys())
        self.assertNotIn("refresh_token_encrypted", row.keys())

    def test_authorization_url_does_not_expose_partner_key(self):
        old = {key: os.environ.get(key) for key in (
            "SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY", "SHOPEE_TOKEN_ENCRYPTION_KEY",
            "APP_PUBLIC_URL",
        )}
        try:
            os.environ.update({
                "SHOPEE_PARTNER_ID": "12345",
                "SHOPEE_PARTNER_KEY": "key-must-never-appear",
                "SHOPEE_TOKEN_ENCRYPTION_KEY": "dGVzdC1vbmx5LW5vdC1hLXJlYWwta2V5LTAwMDAwMDAwMDA=",
                "APP_PUBLIC_URL": "https://dash.example.com",
            })
            url = shopee_api.authorization_url("state-2")
            self.assertNotIn("key-must-never-appear", url)
            parsed = parse_qs(urlparse(url).query)
            self.assertEqual("12345", parsed["partner_id"][0])
            self.assertEqual("state-2", parsed["state"][0])
            self.assertEqual("https://dash.example.com/oauth/shopee/callback", parsed["redirect"][0])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
