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

    def test_selected_sku_update_preserves_other_skus_and_detects_stale_edit(self):
        db.upsert_intelligence_finance_cache(1, "client-guard", {
            "costBySku": {"LAZ-2X2": 10, "LAZ-3X3": 30},
            "fiscalBySku": {"LAZ-2X2": {"evidenceStatus": "user_informed"}},
        }, [])
        saved = db.update_finance_skus(2, "client-guard", [{
            "sku": "LAZ-3X3", "cost": 31, "expectedCost": 30,
            "fiscal": {"evidenceStatus": "pending"}, "expectedFiscal": None,
        }])
        self.assertEqual(saved["costBySku"], {"LAZ-2X2": 10, "LAZ-3X3": 31})
        self.assertEqual(saved["fiscalBySku"]["LAZ-2X2"], {"evidenceStatus": "user_informed"})
        with self.assertRaisesRegex(ValueError, "outra aba"):
            db.update_finance_skus(1, "client-guard", [{
                "sku": "LAZ-3X3", "cost": 40, "expectedCost": 30,
                "fiscal": {}, "expectedFiscal": None,
            }])
        self.assertEqual(db.get_intelligence_finance_cache(1, "client-guard")["profile"]["costBySku"]["LAZ-3X3"], 31)

    def test_legacy_snapshot_cannot_erase_skus_it_did_not_load(self):
        db.upsert_intelligence_finance_cache(1, "client-tabs", {
            "costBySku": {"LAZ-2X2": 10, "LAZ-3X2": 20},
            "fiscalBySku": {"LAZ-2X2": {"evidenceStatus": "pending"}},
        }, [])
        db.upsert_intelligence_finance_cache(2, "client-tabs", {
            "costBySku": {"LAZ-3X2": 21}, "fiscalBySku": {},
        }, [])
        result = db.get_intelligence_finance_cache(1, "client-tabs")["profile"]
        self.assertEqual(result["costBySku"], {"LAZ-2X2": 10, "LAZ-3X2": 21})
        self.assertEqual(result["fiscalBySku"]["LAZ-2X2"], {"evidenceStatus": "pending"})

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


if __name__ == "__main__":
    unittest.main()
