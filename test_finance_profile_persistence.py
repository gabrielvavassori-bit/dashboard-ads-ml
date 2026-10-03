import pathlib
import sqlite3
import tempfile
import unittest

import db


class FinanceProfilePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = pathlib.Path(self.temp.name) / "app.db"
        db.init_db()
        conn = db.get_conn()
        try:
            ts = db.now()
            conn.execute(
                "INSERT INTO users (id,email,status,created_at,updated_at) VALUES (1,'one@test','active',?,?)",
                (ts, ts),
            )
            conn.execute(
                "INSERT INTO users (id,email,status,created_at,updated_at) VALUES (2,'two@test','active',?,?)",
                (ts, ts),
            )
        finally:
            conn.close()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def test_fresh_schema_has_all_durable_finance_columns(self):
        conn = db.get_conn()
        try:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(ml_account_financial_profiles)")
            }
        finally:
            conn.close()
        self.assertTrue({
            "client_id", "cost_by_sku_json", "cost_by_key_json",
            "profit_tax_rate", "flex_carrier_cost", "fiscal_mode",
            "tax_regime", "fiscal_profile_json", "fiscal_by_sku_json",
            "updated_by_user_id", "updated_at",
        }.issubset(columns))

    def test_legacy_profile_is_migrated_without_loss(self):
        conn = db.get_conn()
        try:
            conn.execute(
                """INSERT INTO intelligence_cost_profiles
                   (user_id,client_id,cost_by_sku_json,cost_by_key_json,
                    profit_tax_rate,flex_carrier_cost,updated_at)
                   VALUES (1,'client-legacy','{\"SKU-1\":12.34}','{}',7.5,18,123)"""
            )
        finally:
            conn.close()

        db.init_db()
        profile = db.get_intelligence_finance_cache(2, "client-legacy")["profile"]
        self.assertEqual(profile["costBySku"], {"SKU-1": 12.34})
        self.assertEqual(profile["profitTaxRate"], 7.5)
        self.assertEqual(profile["flexCarrierCost"], 18.0)

    def test_detailed_profile_survives_restart_and_is_shared_by_client(self):
        db.upsert_intelligence_finance_cache(1, "client-shared", {
            "costBySku": {"SKU-REAL": 89.9},
            "costByKey": {},
            "profitTaxRate": 0,
            "flexCarrierCost": 12.5,
            "fiscalMode": "detailed",
            "taxRegime": "real",
            "fiscalProfile": {
                "icmsInputRate": 12,
                "icmsOutputRate": 18,
                "difalEnabled": True,
                "evidenceStatus": "user_informed",
            },
            "fiscalBySku": {"SKU-REAL": {"ipiInputRate": 4}},
        }, [])

        db.init_db()  # simula novo boot/deploy
        profile = db.get_intelligence_finance_cache(2, "client-shared")["profile"]
        self.assertEqual(profile["fiscalMode"], "detailed")
        self.assertEqual(profile["taxRegime"], "real")
        self.assertEqual(profile["fiscalProfile"]["icmsInputRate"], 12)
        self.assertTrue(profile["fiscalProfile"]["difalEnabled"])
        self.assertEqual(profile["fiscalBySku"]["SKU-REAL"]["ipiInputRate"], 4)
        self.assertEqual(profile["updatedByUserId"], 1)

    def test_legacy_update_does_not_erase_detailed_fields(self):
        db.upsert_intelligence_finance_cache(1, "client-preserve", {
            "costBySku": {}, "costByKey": {}, "profitTaxRate": 0,
            "flexCarrierCost": 0, "fiscalMode": "detailed",
            "taxRegime": "presumed",
            "fiscalProfile": {"presumedTaxRate": 5.93},
            "fiscalBySku": {"A": {"cost": 10}},
        }, [])
        db.upsert_intelligence_finance_cache(2, "client-preserve", {
            "costBySku": {"B": 20}, "costByKey": {},
            "profitTaxRate": 6, "flexCarrierCost": 0,
        }, [])

        profile = db.get_intelligence_finance_cache(1, "client-preserve")["profile"]
        self.assertEqual(profile["taxRegime"], "presumed")
        self.assertEqual(profile["fiscalProfile"], {"presumedTaxRate": 5.93})
        self.assertEqual(profile["fiscalBySku"], {"A": {"cost": 10}})
        self.assertEqual(profile["costBySku"], {"B": 20})

    def test_init_repairs_an_older_partial_canonical_table(self):
        conn = db.get_conn()
        try:
            conn.execute("DROP TABLE ml_account_financial_profiles")
            conn.execute("CREATE TABLE ml_account_financial_profiles (client_id TEXT PRIMARY KEY)")
        finally:
            conn.close()

        db.init_db()
        conn = db.get_conn()
        try:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(ml_account_financial_profiles)")
            }
        finally:
            conn.close()
        self.assertIn("fiscal_profile_json", columns)
        self.assertIn("updated_at", columns)

    def test_promotion_bulk_job_persists_progress_and_discards_preview_tokens(self):
        db.create_promotion_bulk_job("job_1234567890123456", 1, "client", [
            {"item_id": "MLB1", "preview_token": "secret", "selection_key": "campaign|MLB1"}
        ])
        queued = db.get_promotion_bulk_job("job_1234567890123456", 1, "client", include_request=True)
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["items"][0]["preview_token"], "secret")
        db.update_promotion_bulk_job(
            "job_1234567890123456", status="completed", completed=1,
            succeeded=1, failed=0, results=[{"item_id": "MLB1", "ok": True}],
            clear_request=True,
        )
        finished = db.get_promotion_bulk_job("job_1234567890123456", 1, "client", include_request=True)
        self.assertEqual(finished["items"], [])
        self.assertEqual(finished["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
