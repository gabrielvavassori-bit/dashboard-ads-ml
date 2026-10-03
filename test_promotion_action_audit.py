import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import db


class PromotionActionAuditTests(unittest.TestCase):
    def test_confirmation_audit_is_persistent_scoped_and_does_not_store_token(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(db, "DB_PATH", pathlib.Path(tmpdir) / "app.db"):
            db.init_db()
            now = db.now()
            conn = db.get_conn()
            try:
                conn.execute(
                    "INSERT INTO users (email,status,created_at,updated_at) VALUES (?,?,?,?)",
                    ("audit@example.com", "active", now, now),
                )
                user_id = conn.execute("SELECT id FROM users WHERE email=?", ("audit@example.com",)).fetchone()["id"]
            finally:
                conn.close()

            db.record_promotion_action(user_id, "client-a", "MLB123", {
                "ok": True,
                "audit_id": "promo-safe",
                "preview_token": "must-not-be-stored",
            })

            rows = db.list_promotion_action_audit(user_id, "client-a")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["item_id"], "MLB123")
            self.assertEqual(rows[0]["status"], "success")
            self.assertEqual(rows[0]["agent_audit_id"], "promo-safe")
            self.assertEqual(db.list_promotion_action_audit(user_id, "client-b"), [])

            conn = db.get_conn()
            try:
                raw = conn.execute("SELECT response_json FROM promotion_action_audit").fetchone()["response_json"]
            finally:
                conn.close()
            self.assertNotIn("must-not-be-stored", raw)
            self.assertNotIn("preview_token", json.loads(raw))


if __name__ == "__main__":
    unittest.main()
