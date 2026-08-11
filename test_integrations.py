import hashlib
import hmac
import importlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = TEST_DIR.name
os.environ["EDUZZ_WEBHOOK_SECRET"] = "local-test-webhook-secret"
os.environ["EDUZZ_PRODUCT_IDS"] = "3032224"
os.environ["EDUZZ_CLIENT_ID"] = "test-client"
os.environ["EDUZZ_CLIENT_SECRET"] = "test-client-secret"
os.environ["APP_PUBLIC_URL"] = "http://127.0.0.1:4182"
os.environ["COMPETITIVE_WORKER_SECRET"] = "local-worker-secret"
os.environ["BETA_MODE"] = "false"
os.environ["BETA_REJECT_BILLING_WEBHOOKS"] = "true"

import db
import auth
import beta_bridge
import eduzz_api
import webhook
import app
from gerar_dashboard_ads_ml import detect_ads_period


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
            conn.execute("DELETE FROM beta_handoffs")
        finally:
            conn.close()
        token_path = pathlib.Path(TEST_DIR.name) / "eduzz_oauth_token.json"
        if token_path.exists():
            token_path.unlink()

    def test_ads_period_accepts_portuguese_month_abbreviations(self):
        ads_rows = [
            (3, {1: "05-jul-2026", 2: "04-ago-2026"}),
        ]
        self.assertEqual(
            detect_ads_period(ads_rows),
            {"dateFrom": "2026-07-05", "dateTo": "2026-08-04"},
        )

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

    def test_paid_invoice_with_past_next_charge_date_falls_back_to_future_access_window(self):
        custom_payload = payload(
            "event-paid-past-due",
            "myeduzz.invoice_paid",
        )
        custom_payload["data"]["contract"]["nextChargeDate"] = "2026-06-01T00:00:00Z"
        raw, signature = signed(custom_payload)
        result = webhook.process_event(raw, signature)
        user = db.get_user_by_email("cliente@example.com")
        self.assertEqual(result["status"], 200)
        self.assertEqual(user["status"], "active")
        self.assertGreater(user["expires_at"], int(app.time.time()) + (30 * 86400))

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

    def test_manual_user_is_promoted_to_eduzz_on_paid_webhook(self):
        db.upsert_manual_user(
            email="manual2eduzz@example.com",
            name="Manual Antes",
            plan="cortesia",
            status="active",
            expires_at=int(app.time.time()) + (7 * 86400),
        )
        custom_payload = payload("event-manual-promote", "myeduzz.invoice_paid")
        custom_payload["data"]["buyer"]["email"] = "manual2eduzz@example.com"
        raw, signature = signed(custom_payload)
        result = webhook.process_event(raw, signature)
        user = db.get_user_by_email("manual2eduzz@example.com")
        self.assertEqual(result["status"], 200)
        self.assertEqual(user["status"], "active")
        self.assertEqual(user["access_origin"], "manual_promoted_eduzz")
        self.assertEqual(user["eduzz_contract_id"], "contract-1")

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
                    """CREATE TABLE user_ml_links (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER NOT NULL,
                       client_id TEXT NOT NULL,
                       status TEXT NOT NULL DEFAULT 'active',
                       created_at INTEGER NOT NULL,
                       updated_at INTEGER NOT NULL,
                       UNIQUE(user_id))"""
                )
                connection.execute(
                    """CREATE TABLE ml_link_states (
                       state_hash TEXT PRIMARY KEY,
                       user_id INTEGER NOT NULL,
                       return_to TEXT NOT NULL,
                       expires_at INTEGER NOT NULL,
                       created_at INTEGER NOT NULL,
                       used_at INTEGER)"""
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
                "ml_cols={r['name'] for r in c.execute("
                "'PRAGMA table_info(user_ml_links)')}; "
                "ml_state_cols={r['name'] for r in c.execute("
                "'PRAGMA table_info(ml_link_states)')}; "
                "row=c.execute(\"SELECT status FROM webhook_events "
                "WHERE event_id='old-event'\").fetchone(); "
                "assert {'payload_hash','status','processed_at','error'} <= cols; "
                "assert {'ml_user_id','nickname','official_store','advertiser_id','seller_id','site_id','last_verified_at'} <= ml_cols; "
                "assert {'attached_at'} <= ml_state_cols; "
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

    def test_subscription_reconciliation_reactivates_existing_expired_eduzz_user(self):
        db.upsert_user_from_webhook(
            email="reativar@example.com",
            name="Cliente Expirado",
            buyer_id="buyer-old",
            contract_id="contract-old",
            plan="ADS ML",
            status="expired",
            expires_at=int(app.time.time()) - 86400,
        )
        original = eduzz_api.request_json
        eduzz_api.request_json = lambda path, params=None: {
            "items": [
                {
                    "id": "contract-reactivate",
                    "status": "upToDate",
                    "productId": "3032224",
                    "customer": {
                        "id": "buyer-new",
                        "name": "Cliente Reativado",
                        "email": "reativar@example.com",
                    },
                    "nextChargeDate": "2030-01-15T00:00:00Z",
                }
            ]
        }
        try:
            result = eduzz_api.reconcile_subscriptions()
        finally:
            eduzz_api.request_json = original
        user = db.get_user_by_email("reativar@example.com")
        self.assertEqual(result["activated"], 1)
        self.assertEqual(user["status"], "active")
        self.assertGreater(user["expires_at"], int(app.time.time()))
        self.assertEqual(user["access_origin"], "eduzz")

    def test_subscription_reconciliation_active_status_never_keeps_past_due_timestamp(self):
        original = eduzz_api.request_json
        eduzz_api.request_json = lambda path, params=None: {
            "items": [
                {
                    "id": "contract-past-due-active",
                    "status": "upToDate",
                    "productId": "3032224",
                    "customer": {
                        "id": "buyer-past",
                        "name": "Cliente Passado",
                        "email": "past-due-active@example.com",
                    },
                    "nextChargeDate": "2026-06-01T00:00:00Z",
                }
            ]
        }
        try:
            result = eduzz_api.reconcile_subscriptions()
        finally:
            eduzz_api.request_json = original
        user = db.get_user_by_email("past-due-active@example.com")
        self.assertEqual(result["activated"], 1)
        self.assertEqual(user["status"], "active")
        self.assertGreater(user["expires_at"], int(app.time.time()) + (30 * 86400))


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

    def _login_cookie(self, email="cliente@example.com"):
        user_id = db.upsert_user_from_webhook(
            email=email,
            name="Cliente Teste",
            buyer_id="buyer-1",
            contract_id="contract-1",
            plan="ADS ML",
            status="active",
            expires_at=None,
        )
        db.set_password(user_id, auth.hash_password("123456"))
        token = auth.new_session_token()
        db.create_session(user_id, token, "127.0.0.1", "tests")
        return user_id, f"{auth.SESSION_COOKIE}={token}"

    def _admin_cookie(self):
        db.ensure_admin("admin@example.com", auth.hash_password("123456"))
        token = auth.create_admin_session("admin@example.com")
        return f"{auth.ADMIN_COOKIE}={token}"

    def _no_redirect_opener(self):
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        return build_opener(NoRedirect)

    def test_beta_assertion_is_identity_only_and_single_use(self):
        user_id, _ = self._login_cookie("beta-assertion@example.com")
        db.set_user_beta_access(user_id, True)
        user = db.get_user_by_id(user_id)
        link = {
            "client_id": "client-1",
            "ml_user_id": "ml-1",
            "nickname": "Lonas Online",
            "official_store": "Lonas Online",
            "advertiser_id": "adv-1",
            "seller_id": "seller-1",
            "site_id": "MLB",
            "status": "active",
        }
        base_now = int(app.time.time())
        token = beta_bridge.create_assertion("secret", user, link, "https://beta.example/beta/callback", now=base_now)
        self.assertNotIn("access_token", token)
        self.assertNotIn("refresh_token", token)
        payload_value = beta_bridge.verify_assertion(token, "secret", "https://beta.example/beta/callback", now=base_now + 1)
        self.assertEqual(payload_value["user"]["email"], "beta-assertion@example.com")
        self.assertIs(payload_value["user"]["beta_enabled"], True)
        self.assertEqual(payload_value["ml"]["client_id"], "client-1")
        self.assertTrue(db.claim_beta_handoff(payload_value["nonce"], payload_value["exp"]))
        self.assertFalse(db.claim_beta_handoff(payload_value["nonce"], payload_value["exp"]))

    def test_beta_assertion_rejects_tamper_and_expiry(self):
        user_id, _ = self._login_cookie("beta@example.com")
        user = db.get_user_by_id(user_id)
        token = beta_bridge.create_assertion("secret", user, None, "https://beta.example/beta/callback", now=100)
        body, signature = token.split(".", 1)
        tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + signature
        with self.assertRaises(ValueError):
            beta_bridge.verify_assertion(tampered, "secret", "https://beta.example/beta/callback", now=101)
        with self.assertRaises(ValueError):
            beta_bridge.verify_assertion(token, "secret", "https://beta.example/beta/callback", now=221)

    def test_sync_beta_access_posts_signed_assertion(self):
        user_id, _ = self._login_cookie("beta-sync@example.com")
        db.set_user_beta_access(user_id, True)
        user = db.get_user_by_id(user_id)
        received = {}

        class FakeBeta(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                token = form.get("assertion", [""])[0]
                audience = f"http://127.0.0.1:{self.server.server_port}/internal/beta/access-sync"
                received.update(beta_bridge.verify_assertion(token, "sync-secret", audience))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeBeta)
        thread = threading.Thread(target=fake.serve_forever, daemon=True)
        thread.start()
        original_secret = app.beta_config.BETA_SHARED_AUTH_SECRET
        original_public_url = app.beta_config.BETA_PUBLIC_URL
        app.beta_config.BETA_SHARED_AUTH_SECRET = "sync-secret"
        app.beta_config.BETA_PUBLIC_URL = f"http://127.0.0.1:{fake.server_port}"
        try:
            self.assertTrue(app._sync_beta_access(user))
            self.assertIs(received["user"]["beta_enabled"], True)
        finally:
            app.beta_config.BETA_SHARED_AUTH_SECRET = original_secret
            app.beta_config.BETA_PUBLIC_URL = original_public_url
            fake.shutdown()
            fake.server_close()
            thread.join(timeout=3)

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

    def test_beta_entry_is_disabled_by_default(self):
        original = app.beta_config.BETA_MODE
        app.beta_config.BETA_MODE = False
        try:
            request = Request(f"{self.base_url}/teste", method="GET")
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 404)
            raised.exception.close()
        finally:
            app.beta_config.BETA_MODE = original

    def test_beta_entry_requires_allowlist_and_shows_isolation(self):
        user_id, cookie = self._login_cookie("beta@example.com")
        original = (
            app.beta_config.BETA_MODE,
            app.beta_config.BETA_ALLOWED_EMAILS,
            app.beta_config.BETA_SHARED_AUTH_URL,
            app.beta_config.BETA_SHARED_AUTH_SECRET,
            app.beta_config.BETA_SHARED_ML_URL,
        )
        app.beta_config.BETA_MODE = True
        app.beta_config.BETA_ALLOWED_EMAILS = frozenset()
        try:
            request = Request(f"{self.base_url}/teste", headers={"Cookie": cookie}, method="GET")
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 403)
            raised.exception.close()
            app.beta_config.BETA_ALLOWED_EMAILS = frozenset({"beta@example.com"})
            app.beta_config.BETA_SHARED_AUTH_URL = "https://auth.example.test"
            app.beta_config.BETA_SHARED_AUTH_SECRET = "test-secret"
            app.beta_config.BETA_SHARED_ML_URL = "https://ml.example.test"
            request = Request(f"{self.base_url}/teste", headers={"Cookie": cookie}, method="GET")
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace")
            self.assertEqual(response.status, 200)
            self.assertIn("Ambiente beta privado", body)
            self.assertIn("Ponte compartilhada de identidade/OAuth", body)
            self.assertIn("bloqueados neste beta", body)
        finally:
            (
                app.beta_config.BETA_MODE,
                app.beta_config.BETA_ALLOWED_EMAILS,
                app.beta_config.BETA_SHARED_AUTH_URL,
                app.beta_config.BETA_SHARED_AUTH_SECRET,
                app.beta_config.BETA_SHARED_ML_URL,
            ) = original

    def test_beta_rejects_billing_delivery(self):
        original = (app.beta_config.BETA_MODE, app.beta_config.BETA_REJECT_BILLING_WEBHOOKS)
        app.beta_config.BETA_MODE = True
        app.beta_config.BETA_REJECT_BILLING_WEBHOOKS = True
        try:
            request = Request(
                f"{self.base_url}/eduzz/custom-delivery",
                data=b'{"test":true}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 404)
            self.assertIn("desativada no ambiente beta", raised.exception.read().decode("utf-8", errors="replace"))
        finally:
            app.beta_config.BETA_MODE, app.beta_config.BETA_REJECT_BILLING_WEBHOOKS = original

    def test_dash_ads_diagnostic_proxy_requires_secret(self):
        request = Request(f"{self.base_url}/internal/dash-ads/ml-context?client=conta-ativa", method="GET")
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 401)
        raised.exception.close()

    def test_dash_ads_diagnostic_proxy_sanitizes_response(self):
        seen = {}

        class FakeAgenteML(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_GET(self):
                seen.setdefault("paths", []).append(self.path)
                seen["secret"] = self.headers.get("X-COMPETITIVE-WORKER-SECRET")
                body = json.dumps({
                    "ok": True,
                    "client_id": "conta-ativa",
                    "ml_user_id": 14252670,
                    "nickname": "LONAS_ONLINE",
                    "advertiser_id": "164424",
                    "access_token": "nao-deve-voltar",
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgenteML)
        thread = threading.Thread(target=fake.serve_forever, daemon=True)
        original_base = app.AGENTE_ML_BASE_URL
        app.AGENTE_ML_BASE_URL = f"http://127.0.0.1:{fake.server_port}"
        thread.start()
        try:
            request = Request(
                f"{self.base_url}/internal/dash-ads/ml-context?client=conta-ativa&bad=ignored",
                headers={"X-COMPETITIVE-WORKER-SECRET": os.environ["COMPETITIVE_WORKER_SECRET"]},
                method="GET",
            )
            with urlopen(request, timeout=5) as response:
                body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(body["client_id"], "conta-ativa")
            self.assertEqual(body["advertiser_id"], "164424")
            self.assertFalse(body["token_exposed"])
            self.assertNotIn("access_token", body)
            self.assertEqual(seen["secret"], os.environ["COMPETITIVE_WORKER_SECRET"])
            self.assertEqual(seen["paths"][0], "/internal/dash-ads/ml-context?client=conta-ativa")
            request = Request(
                f"{self.base_url}/internal/dash-ads/online-cache-refresh?client=conta-ativa&max_items=3&bad=ignored",
                headers={"X-COMPETITIVE-WORKER-SECRET": os.environ["COMPETITIVE_WORKER_SECRET"]},
                method="GET",
            )
            with urlopen(request, timeout=5) as response:
                cache_body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertTrue(cache_body["ok"])
            self.assertNotIn("access_token", cache_body)
            self.assertEqual(seen["paths"][1], "/internal/dash-ads/online-cache-refresh?client=conta-ativa&max_items=3")
        finally:
            app.AGENTE_ML_BASE_URL = original_base
            fake.shutdown()
            fake.server_close()
            thread.join(timeout=3)

    def test_online_renders_dash_ads_when_link_exists(self):
        user_id, cookie = self._login_cookie("linked@example.com")
        db.upsert_user_ml_link(
            user_id,
            client_id="conta-ativa",
            ml_user_id="14252670",
            nickname="LONAS_ONLINE",
            advertiser_id="164424",
        )
        original = app._build_online_dashboard_data
        app._build_online_dashboard_data = lambda *_args, **_kwargs: ({
            "kpis": {"clientName": "LONAS_ONLINE", "products": 0, "units": 0, "revenue": 0, "adsRevenue": 0, "adsDirectRevenue": 0, "organicRevenue": 0, "tacosBaseRevenue": 0, "investment": 0, "investmentNoAdsSales": 0, "cvr": 0, "tacos": 0, "roas": 0, "adsNoSales": 0, "adsOnlyNoTotalSales": 0, "tacosHigh": 0, "salesNoAds": 0},
            "meta": {"onlineMode": {"notice": "Modo online beta: dados parciais."}},
            "items": [], "decisionItems": [], "adsNoSales": [], "highTacos": [], "salesNoAds": [], "skuAds": [], "campaignAds": [], "adsByProduct": [], "finishedNoSku": [], "onlineBeta": {"enabled": True},
        }, "")
        try:
            request = Request(f"{self.base_url}/online?confirmed=1", headers={"Cookie": cookie}, method="GET")
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace")
            self.assertEqual(response.status, 200)
            self.assertIn("Dashboard ADS Mercado Livre", body)
            self.assertIn("Modo online beta: dados parciais.", body)
            self.assertIn('data-view-mode="campaign"', body)
            self.assertIn("Ver leitura", body)
            self.assertIn("Dependencia de Ads &gt; 50%", body)
            self.assertNotIn("agente-ml.onrender.com/relatorio", body)
            scripts = "\n".join(re.findall(r"<script>(.*?)</script>", body, flags=re.S))
            syntax = subprocess.run(
                ["node", "--check", "-"],
                input=scripts,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
        finally:
            app._build_online_dashboard_data = original

    def test_online_dashboard_deduplicates_exact_ads_cache_rows(self):
        duplicate_row = {
            "item_id": "MLB123",
            "campaign_id": "456",
            "status": "active",
            "sku": "SKU-123",
            "title": "Produto Teste",
            "cost": 10,
            "total_amount": 100,
            "direct_amount": 70,
            "units_quantity": 2,
            "prints": 1000,
            "clicks": 50,
            "price": 50,
        }
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": True}},
            "ads": {"items": [dict(duplicate_row), dict(duplicate_row)]},
            "sales": {"items": {"MLB123": {"revenue_total": 200, "units_total": 4}}},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        self.assertEqual(data["kpis"]["products"], 1)
        self.assertEqual(data["kpis"]["investment"], 10)
        self.assertEqual(data["kpis"]["adsRevenue"], 100)
        self.assertEqual(data["kpis"]["revenue"], 200)
        self.assertEqual(data["items"][0]["organicRevenue"], 130)
        self.assertEqual(data["items"][0]["tacosBaseRevenue"], 230)
        self.assertAlmostEqual(data["items"][0]["tacos"], 10 / 230)
        self.assertEqual(data["kpis"]["organicRevenue"], 130)
        self.assertEqual(data["kpis"]["tacosBaseRevenue"], 200)
        self.assertAlmostEqual(data["kpis"]["tacos"], 0.05)
        self.assertEqual(data["meta"]["adsDeduplication"]["removedRows"], 1)
        self.assertIn("linhas duplicadas exatas", data["meta"]["onlineMode"]["notice"])

    def test_online_dashboard_uses_enriched_cache_metadata(self):
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": True}},
            "ads": {"items": [{
                "item_id": "MLB123",
                "campaign_id": "456",
                "campaign_name": "Campanha Principal",
                "sku": "SKU-123",
                "title": "Produto Teste",
                "price": 59.9,
            }]},
            "sales": {"items": {"MLB123": {
                "revenue_total": 100,
                "units_total": 2,
                "last_sale_date": "2026-07-30T10:00:00-03:00",
                "last_price": 49.9,
            }}},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        item = data["items"][0]
        self.assertEqual(item["sku"], "SKU-123")
        self.assertEqual(item["title"], "Produto Teste")
        self.assertEqual(item["campaign"], "Campanha Principal")
        self.assertEqual(item["lastSaleDate"], "2026-07-30T10:00:00-03:00")
        self.assertEqual(item["lastPrice"], 49.9)

    def test_online_dashboard_counts_sales_once_for_same_item_in_different_campaigns(self):
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": True}},
            "ads": {"items": [
                {"item_id": "MLB123", "campaign_id": "A", "cost": 10, "total_amount": 100},
                {"item_id": "MLB123", "campaign_id": "B", "cost": 5, "total_amount": 50},
            ]},
            "sales": {"items": {"MLB123": {"revenue_total": 200, "units_total": 4}}},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        self.assertEqual(data["kpis"]["revenue"], 200)
        self.assertEqual(data["kpis"]["units"], 4)
        self.assertEqual(data["kpis"]["organicRevenue"], 200)
        self.assertEqual(data["kpis"]["tacosBaseRevenue"], 200)
        self.assertEqual(len(data["campaignAds"]), 2)
        self.assertTrue(all(item["campaignRevenueAmbiguous"] for item in data["campaignAds"]))
        self.assertTrue(all(item["confidence"] == "hipotese" for item in data["campaignAds"]))

    def test_online_dashboard_includes_sales_without_ads_rows(self):
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": True}},
            "ads": {"items": [{"item_id": "MLB123", "cost": 10, "total_amount": 100}]},
            "sales": {"items": {
                "MLB123": {"revenue_total": 200, "units_total": 4},
                "MLB456": {"revenue_total": 300, "units_total": 2, "sku": "SKU-456"},
            }},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        self.assertEqual(data["kpis"]["products"], 2)
        self.assertEqual(data["kpis"]["revenue"], 500)
        self.assertEqual(data["kpis"]["units"], 6)
        self.assertEqual(data["items"][1]["code"], "MLB456")

    def test_online_product_tacos_uses_indirect_revenue_without_product_sale(self):
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": True}},
            "ads": {"items": [{"item_id": "MLB123", "cost": 2000, "total_amount": 50000, "direct_amount": 0}]},
            "sales": {"items": {"MLB123": {"revenue_total": 0, "units_total": 0}}},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        self.assertEqual(data["items"][0]["tacosBaseRevenue"], 50000)
        self.assertAlmostEqual(data["items"][0]["tacos"], 0.04)
        self.assertEqual(data["kpis"]["tacosBaseRevenue"], 0)

    def test_online_dashboard_marks_partial_sales_in_diagnostics(self):
        payload = {
            "ok": True,
            "latest": {"date_from": "2026-07-01", "date_to": "2026-07-30", "sales": {"complete": False}},
            "ads": {"items": [{"item_id": "MLB123", "campaign_id": "A", "cost": 10, "total_amount": 100}]},
            "sales": {"items": {"MLB123": {"revenue_total": 50, "units_total": 1}}},
        }
        original_fetch = app._fetch_dash_ads_json
        app._fetch_dash_ads_json = lambda *_args, **_kwargs: payload
        try:
            data, message = app._build_online_dashboard_data("conta-ativa", "164424")
        finally:
            app._fetch_dash_ads_json = original_fetch

        self.assertEqual(message, "")
        self.assertFalse(data["items"][0]["salesCoverageComplete"])
        self.assertIn("leitura parcial", data["items"][0]["diagnosticSummary"])
        self.assertIn("faturamento e TACOS", " ".join(data["items"][0]["validationPoints"]))

    def test_online_requires_beta_confirmation_before_redirect(self):
        user_id, cookie = self._login_cookie("warn@example.com")
        db.upsert_user_ml_link(
            user_id,
            client_id="conta-aviso",
            ml_user_id="14252670",
            nickname="LONAS_ONLINE",
            advertiser_id="164424",
        )
        request = Request(f"{self.base_url}/online", headers={"Cookie": cookie}, method="GET")
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
        self.assertEqual(response.status, 200)
        self.assertIn("Modo online beta", body)
        self.assertIn("fase de testes", body)
        self.assertIn("/online?confirmed=1", body)

    def test_internal_ml_link_attach_and_finish_flow(self):
        user_id, cookie = self._login_cookie("attach@example.com")
        bridge_state = "mlink-test-state"
        db.save_ml_link_state(bridge_state, user_id, return_to="/online?confirmed=1")
        payload = json.dumps({
            "bridge_state": bridge_state,
            "client_id": "conta-ativa",
            "ml_user_id": "14252670",
            "nickname": "LONAS_ONLINE",
            "official_store": "Lonas Online",
            "advertiser_id": "164424",
            "seller_id": "seller-1",
            "site_id": "MLB",
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/internal/ml-link/attach",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Secret": os.environ["COMPETITIVE_WORKER_SECRET"],
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            body = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertTrue(body["ok"])
        link = db.get_active_ml_link_for_user(user_id)
        self.assertEqual(link["client_id"], "conta-ativa")
        opener = self._no_redirect_opener()
        finish_request = Request(
            f"{self.base_url}/ml-link/finish?state={bridge_state}",
            headers={"Cookie": cookie},
            method="GET",
        )
        with self.assertRaises(HTTPError) as raised:
            opener.open(finish_request, timeout=5)
        self.assertEqual(raised.exception.code, 302)
        self.assertEqual(raised.exception.headers.get("Location"), "/online?confirmed=1")
        raised.exception.close()

    def test_admin_can_create_manual_access_with_expiration(self):
        admin_cookie = self._admin_cookie()
        payload = urlencode({
            "email": "manual@example.com",
            "name": "Manual Teste",
            "plan": "cortesia",
            "days": "7",
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/users/manual_access",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin_cookie,
            },
            method="POST",
        )
        opener = self._no_redirect_opener()
        with self.assertRaises(HTTPError) as raised:
            opener.open(request, timeout=5)
        self.assertEqual(raised.exception.code, 302)
        user = db.get_user_by_email("manual@example.com")
        self.assertIsNotNone(user)
        self.assertEqual(user["status"], "active")
        self.assertEqual(user["plan"], "cortesia")
        self.assertGreater(user["expires_at"], int(app.time.time()) + (6 * 86400))
        raised.exception.close()

    def test_admin_can_allow_and_block_beta_without_changing_real_access(self):
        user_id = db.upsert_manual_user(
            email="beta-toggle@example.com",
            name="Cliente Beta",
            plan="cortesia",
            status="active",
            expires_at=None,
        )
        admin_cookie = self._admin_cookie()
        opener = self._no_redirect_opener()
        original_sync = app._sync_beta_access
        app._sync_beta_access = lambda user: True
        try:
            for enabled, expected in (("1", 1), ("0", 0)):
                request = Request(
                    f"{self.base_url}/admin/users/{user_id}/set_beta_access",
                    data=urlencode({"enabled": enabled}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Cookie": admin_cookie,
                    },
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    opener.open(request, timeout=5)
                self.assertEqual(raised.exception.code, 302)
                raised.exception.close()
                user = db.get_user_by_id(user_id)
                self.assertEqual(user["beta_enabled"], expected)
                self.assertEqual(user["status"], "active")
                self.assertEqual(user["access_origin"], "manual")
                self.assertIsNone(user["expires_at"])
        finally:
            app._sync_beta_access = original_sync

        request = Request(
            f"{self.base_url}/admin?q=beta-toggle%40example.com",
            headers={"Cookie": admin_cookie},
            method="GET",
        )
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
        self.assertIn("Beta bloqueado", body)
        self.assertIn("Liberar beta", body)
        self.assertIn(f"/admin/users/{user_id}/set_beta_access", body)

    def test_admin_can_allow_and_block_sales_intelligence_access(self):
        user_id = db.upsert_manual_user(
            email="sales-toggle@example.com",
            name="Cliente Vendas",
            plan="cortesia",
            status="active",
            expires_at=None,
        )
        admin_cookie = self._admin_cookie()
        opener = self._no_redirect_opener()

        for enabled, expected, expected_label in (("0", 0, "Vendas bloqueada"), ("1", 1, "Vendas liberada")):
            request = Request(
                f"{self.base_url}/admin/users/{user_id}/set_sales_access",
                data=urlencode({"enabled": enabled}).encode("utf-8"),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": admin_cookie,
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                opener.open(request, timeout=5)
            self.assertEqual(raised.exception.code, 302)
            raised.exception.close()
            user = db.get_user_by_id(user_id)
            self.assertEqual(user["sales_enabled"], expected)

            request = Request(
                f"{self.base_url}/admin?q=sales-toggle%40example.com",
                headers={"Cookie": admin_cookie},
                method="GET",
            )
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace")
            self.assertIn(expected_label, body)
            self.assertIn(f"/admin/users/{user_id}/set_sales_access", body)

    def test_beta_access_sync_blocks_user_and_ends_beta_session(self):
        user_id, cookie = self._login_cookie("beta-block@example.com")
        db.set_user_beta_access(user_id, False)
        user = db.get_user_by_id(user_id)
        original_mode = app.beta_config.BETA_MODE
        original_secret = app.beta_config.BETA_SHARED_AUTH_SECRET
        original_public_url = app.beta_config.BETA_PUBLIC_URL
        app.beta_config.BETA_MODE = True
        app.beta_config.BETA_SHARED_AUTH_SECRET = "sync-secret"
        app.beta_config.BETA_PUBLIC_URL = self.base_url
        try:
            audience = f"{self.base_url}/internal/beta/access-sync"
            token = beta_bridge.create_assertion("sync-secret", user, None, audience)
            request = Request(
                audience,
                data=urlencode({"assertion": token}).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                result = json.loads(response.read())
            self.assertTrue(result["ok"])
            session_token = cookie.split("=", 1)[1]
            self.assertIsNone(db.get_session(session_token))
            self.assertEqual(db.get_user_by_id(user_id)["beta_enabled"], 0)
        finally:
            app.beta_config.BETA_MODE = original_mode
            app.beta_config.BETA_SHARED_AUTH_SECRET = original_secret
            app.beta_config.BETA_PUBLIC_URL = original_public_url
    def test_admin_can_bind_ml_link_manually_for_existing_user(self):
        user_id = db.upsert_manual_user(
            email="lonas@example.com",
            name="Lonas Online",
            plan="cortesia",
            status="active",
            expires_at=None,
        )
        admin_cookie = self._admin_cookie()
        payload = urlencode({
            "email": "lonas@example.com",
            "client_id": "conta-ativa",
            "ml_user_id": "14252670",
            "nickname": "LONAS_ONLINE",
            "official_store": "Lonas Online",
            "advertiser_id": "164424",
            "site_id": "MLB",
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/users/bind_ml_link",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin_cookie,
            },
            method="POST",
        )
        opener = self._no_redirect_opener()
        with self.assertRaises(HTTPError) as raised:
            opener.open(request, timeout=5)
        self.assertEqual(raised.exception.code, 302)
        link = db.get_active_ml_link_for_user(user_id)
        self.assertIsNotNone(link)
        self.assertEqual(link["client_id"], "conta-ativa")
        self.assertEqual(link["ml_user_id"], "14252670")
        self.assertEqual(link["advertiser_id"], "164424")
        raised.exception.close()

    def test_sales_intelligence_route_requires_permission(self):
        user_id, cookie = self._login_cookie("sales-route@example.com")

        request = Request(
            f"{self.base_url}/inteligencia-vendas",
            headers={"Cookie": cookie},
            method="GET",
        )
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
        self.assertIn("Inteligencia de Vendas Marketplace", body)

        db.set_user_sales_access(user_id, False)
        blocked_request = Request(
            f"{self.base_url}/inteligencia-vendas",
            headers={"Cookie": cookie},
            method="GET",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(blocked_request, timeout=5)
        self.assertEqual(raised.exception.code, 403)
        blocked_body = raised.exception.read().decode("utf-8", errors="replace")
        self.assertIn("Inteligencia de Vendas esta bloqueada", blocked_body)
        raised.exception.close()

    def test_admin_can_extend_existing_user_for_x_days(self):
        user_id = db.upsert_manual_user(
            email="renew@example.com",
            name="Cliente Renovado",
            plan="cortesia",
            status="suspended",
            expires_at=None,
        )
        admin_cookie = self._admin_cookie()
        payload = urlencode({"days": "15"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/users/{user_id}/grant_access",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin_cookie,
            },
            method="POST",
        )
        opener = self._no_redirect_opener()
        with self.assertRaises(HTTPError) as raised:
            opener.open(request, timeout=5)
        self.assertEqual(raised.exception.code, 302)
        user = db.get_user_by_id(user_id)
        self.assertEqual(user["status"], "active")
        self.assertGreater(user["expires_at"], int(app.time.time()) + (14 * 86400))
        raised.exception.close()

    def test_manual_user_keeps_manual_origin_after_admin_extension(self):
        user_id = db.upsert_manual_user(
            email="manual-origin@example.com",
            name="Origem Manual",
            plan="cortesia",
            status="active",
            expires_at=None,
        )
        admin_cookie = self._admin_cookie()
        payload = urlencode({"days": "10"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/users/{user_id}/grant_access",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin_cookie,
            },
            method="POST",
        )
        opener = self._no_redirect_opener()
        with self.assertRaises(HTTPError):
            opener.open(request, timeout=5)
        user = db.get_user_by_id(user_id)
        self.assertEqual(user["access_origin"], "manual")

    def test_admin_activate_clears_expired_access_window(self):
        user_id = db.upsert_manual_user(
            email="expired-activate@example.com",
            name="Expirado Reativado",
            plan="cortesia",
            status="expired",
            expires_at=int(app.time.time()) - 86400,
        )
        admin_cookie = self._admin_cookie()
        payload = urlencode({"status": "active"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/users/{user_id}/set_status",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin_cookie,
            },
            method="POST",
        )
        opener = self._no_redirect_opener()
        with self.assertRaises(HTTPError) as raised:
            opener.open(request, timeout=5)
        self.assertEqual(raised.exception.code, 302)
        user = db.get_user_by_id(user_id)
        self.assertEqual(user["status"], "active")
        self.assertIsNone(user["expires_at"])
        self.assertTrue(auth.user_is_active(user))
        raised.exception.close()

    def test_list_users_normalizes_overdue_active_users(self):
        db.upsert_manual_user(
            email="overdue-list@example.com",
            name="Expirado na Lista",
            plan="cortesia",
            status="active",
            expires_at=int(app.time.time()) - 3600,
        )
        users = db.list_users("overdue-list@example.com")
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["status"], "expired")

    def test_get_session_normalizes_overdue_active_user(self):
        user_id = db.upsert_manual_user(
            email="overdue-session@example.com",
            name="Expirado na Sessao",
            plan="cortesia",
            status="active",
            expires_at=int(app.time.time()) - 3600,
        )
        token = auth.new_session_token()
        db.create_session(user_id, token, "127.0.0.1", "tests")
        sess = db.get_session(token)
        self.assertEqual(sess["status"], "expired")
        self.assertFalse(auth.user_is_active(sess))


if __name__ == "__main__":
    unittest.main(verbosity=2)
