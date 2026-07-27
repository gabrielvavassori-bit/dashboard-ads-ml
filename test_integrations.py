import hashlib
import hmac
import importlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = TEST_DIR.name
os.environ["EDUZZ_WEBHOOK_SECRET"] = "local-test-webhook-secret"
os.environ["EDUZZ_PRODUCT_IDS"] = "3032224"
os.environ["EDUZZ_CLIENT_ID"] = "test-client"
os.environ["EDUZZ_CLIENT_SECRET"] = "test-client-secret"
os.environ["APP_PUBLIC_URL"] = "http://127.0.0.1:4182"

import db
import eduzz_api
import webhook
import app


def signed(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        os.environ["EDUZZ_WEBHOOK_SECRET"].encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, signature


def payload(event_id, event_name, status="upToDate", product_id="3032224"):
    return {
        "id": event_id,
        "event": event_name,
        "data": {
            "buyer": {
                "id": "buyer-1",
                "name": "Cliente Teste",
                "email": "cliente@example.com",
                "document": "nao-deve-ser-persistido",
            },
            "contract": {
                "id": "contract-1",
                "status": status,
                "nextChargeDate": "2030-01-01T00:00:00Z",
            },
            "offer": {"name": "ADS ML"},
            "items": [{"productId": product_id}],
        },
    }


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def tearDown(self):
        conn = db.get_conn()
        try:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM webhook_events")
            conn.execute("DELETE FROM oauth_states")
            conn.execute("DELETE FROM audit_log")
        finally:
            conn.close()
        token_path = pathlib.Path(TEST_DIR.name) / "eduzz_oauth_token.json"
        if token_path.exists():
            token_path.unlink()

    def test_paid_invoice_uses_items_product_id_and_is_idempotent(self):
        raw, signature = signed(payload(
            "event-paid",
            "myeduzz.invoice_paid",
        ))
        first = webhook.process_event(raw, signature)
        second = webhook.process_event(raw, signature)
        user = db.get_user_by_email("cliente@example.com")
        event = db.get_webhook_event("event-paid")
        self.assertEqual(first["status"], 200)
        self.assertEqual(second["message"], "Evento ja processado")
        self.assertEqual(user["status"], "active")
        self.assertEqual(event["status"], "processed")
        self.assertNotIn("cliente@example.com", event["payload"])
        self.assertNotIn("nao-deve-ser-persistido", event["payload"])

    def test_wrong_product_is_ignored(self):
        raw, signature = signed(payload(
            "event-wrong-product",
            "myeduzz.invoice_paid",
            product_id="999",
        ))
        result = webhook.process_event(raw, signature)
        event = db.get_webhook_event("event-wrong-product")
        self.assertEqual(result["status"], 200)
        self.assertIsNone(db.get_user_by_email("cliente@example.com"))
        self.assertEqual(event["status"], "ignored")

    def test_contract_created_requires_eligible_status(self):
        raw, signature = signed(payload(
            "event-contract-canceled",
            "myeduzz.contract_created",
            status="canceled",
        ))
        result = webhook.process_event(raw, signature)
        self.assertEqual(result["status"], 200)
        self.assertIsNone(db.get_user_by_email("cliente@example.com"))

        raw, signature = signed(payload(
            "event-contract-trial",
            "myeduzz.contract_created",
            status="trial",
        ))
        result = webhook.process_event(raw, signature)
        self.assertEqual(result["status"], 200)
        self.assertEqual(
            db.get_user_by_email("cliente@example.com")["status"],
            "active",
        )

    def test_failed_event_can_be_retried(self):
        raw, signature = signed(payload(
            "event-retry",
            "myeduzz.invoice_paid",
        ))
        original = db.upsert_user_from_webhook

        def fail_once(**kwargs):
            raise RuntimeError("temporary database failure")

        db.upsert_user_from_webhook = fail_once
        try:
            first = webhook.process_event(raw, signature)
        finally:
            db.upsert_user_from_webhook = original
        self.assertEqual(first["status"], 500)
        self.assertEqual(db.get_webhook_event("event-retry")["status"], "failed")

        second = webhook.process_event(raw, signature)
        self.assertEqual(second["status"], 200)
        self.assertEqual(db.get_webhook_event("event-retry")["status"], "processed")

    def test_invalid_signature_is_rejected(self):
        raw, _ = signed(payload("event-signature", "myeduzz.invoice_paid"))
        result = webhook.process_event(raw, "invalid")
        self.assertEqual(result["status"], 401)
        self.assertIsNone(db.get_webhook_event("event-signature"))

    def test_existing_database_schema_is_migrated(self):
        with tempfile.TemporaryDirectory() as old_data_dir:
            old_db = pathlib.Path(old_data_dir) / "app.db"
            connection = sqlite3.connect(old_db)
            try:
                connection.execute(
                    """CREATE TABLE webhook_events (
                       event_id TEXT PRIMARY KEY,
                       event_name TEXT NOT NULL,
                       received_at INTEGER NOT NULL,
                       payload TEXT NOT NULL)"""
                )
                connection.execute(
                    "INSERT INTO webhook_events VALUES (?,?,?,?)",
                    ("old-event", "myeduzz.invoice_paid", 1, "{}"),
                )
                connection.commit()
            finally:
                connection.close()
            env = os.environ.copy()
            env["DATA_DIR"] = old_data_dir
            code = (
                "import db; db.init_db(); "
                "c=db.get_conn(); "
                "cols={r['name'] for r in c.execute("
                "'PRAGMA table_info(webhook_events)')}; "
                "row=c.execute(\"SELECT status FROM webhook_events "
                "WHERE event_id='old-event'\").fetchone(); "
                "assert {'payload_hash','status','processed_at','error'} <= cols; "
                "assert row['status']=='processed'; c.close()"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=pathlib.Path(__file__).parent,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_oauth_state_is_one_time(self):
        url = eduzz_api.authorization_url()
        query = parse_qs(urlparse(url).query)
        state = query["state"][0]
        self.assertEqual(query["client_id"][0], "test-client")
        self.assertTrue(db.consume_oauth_state(state))
        self.assertFalse(db.consume_oauth_state(state))

    def test_subscription_reconciliation_is_conservative(self):
        original = eduzz_api.request_json
        eduzz_api.request_json = lambda path, params=None: {
            "items": [
                {
                    "id": "contract-active",
                    "status": "upToDate",
                    "productId": "3032224",
                    "customer": {
                        "id": "buyer-api",
                        "name": "Cliente API",
                        "email": "api@example.com",
                    },
                    "nextChargeDate": "2030-01-01T00:00:00Z",
                },
                {
                    "id": "contract-unknown",
                    "status": "futureNewStatus",
                    "productId": "3032224",
                    "customer": {"email": "unknown@example.com"},
                },
            ]
        }
        try:
            result = eduzz_api.reconcile_subscriptions()
        finally:
            eduzz_api.request_json = original
        self.assertEqual(result["activated"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(db.get_user_by_email("api@example.com")["status"], "active")
        self.assertIsNone(db.get_user_by_email("unknown@example.com"))


class HTTPRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_health_and_custom_delivery(self):
        with urlopen(f"{self.base_url}/healthz", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])
        request = Request(
            f"{self.base_url}/eduzz/custom-delivery",
            data=b'{"test":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertTrue(body["success"])
            self.assertEqual(body["access_url"], app.APP_PUBLIC_URL)

    def test_reconcile_rejects_missing_secret(self):
        request = Request(
            f"{self.base_url}/internal/eduzz/reconcile",
            data=b"",
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 401)
        raised.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
