"""
Eduzz OAuth2 client and subscription reconciliation.

The webhook remains the primary real-time integration. This client is a
recovery layer: it reconciles subscriptions when a webhook is delayed or
missed. Secrets are read from environment variables and tokens are stored on
the persistent Render disk, never in source control.
"""
import json
import os
import pathlib
import secrets
import time
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import db

AUTHORIZE_URL = "https://accounts.eduzz.com/oauth/authorize"
TOKEN_URL = "https://accounts-api.eduzz.com/oauth/token"
API_BASE_URL = "https://api.eduzz.com"

DEFAULT_SCOPES = (
    "myeduzz_products_read "
    "myeduzz_subscriptions_read "
    "myeduzz_sales_read "
    "myeduzz_customers_read "
    "webhook_read webhook_write"
)


class EduzzAPIError(RuntimeError):
    pass


def _config():
    public_url = os.environ.get(
        "APP_PUBLIC_URL",
        "https://dashboard-ads-ml.onrender.com",
    ).rstrip("/")
    data_dir = pathlib.Path(os.environ.get("DATA_DIR", "./data"))
    return {
        "client_id": os.environ.get("EDUZZ_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("EDUZZ_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get(
            "EDUZZ_OAUTH_REDIRECT_URI",
            f"{public_url}/oauth/eduzz/callback",
        ).strip(),
        "scopes": os.environ.get("EDUZZ_OAUTH_SCOPES", DEFAULT_SCOPES).strip(),
        "token_path": data_dir / "eduzz_oauth_token.json",
    }


def is_configured() -> bool:
    cfg = _config()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def _load_token():
    path = _config()["token_path"]
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_token(token: dict):
    cfg = _config()
    path = cfg["token_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        key: value for key, value in token.items()
        if key in (
            "access_token",
            "refresh_token",
            "token_type",
            "scope",
            "expires_in",
            "expires_at",
        )
    }
    if clean.get("expires_in") and not clean.get("expires_at"):
        clean["expires_at"] = int(time.time()) + int(clean["expires_in"])
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(clean, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )
    try:
        os.chmod(temp_path, 0o600)
    except OSError:
        pass
    temp_path.replace(path)


def connection_status() -> dict:
    token = _load_token()
    expires_at = int((token or {}).get("expires_at") or 0)
    return {
        "configured": is_configured(),
        "connected": bool(token and token.get("access_token")),
        "expires_at": expires_at or None,
        "refresh_available": bool(token and token.get("refresh_token")),
    }


def authorization_url() -> str:
    if not is_configured():
        raise EduzzAPIError("EDUZZ_CLIENT_ID/EDUZZ_CLIENT_SECRET nao configurados.")
    cfg = _config()
    state = secrets.token_urlsafe(32)
    db.save_oauth_state(state)
    query = urlencode({
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": cfg["scopes"],
        "state": state,
    })
    return f"{AUTHORIZE_URL}?{query}"


def _form_request(url: str, form: dict) -> dict:
    request = Request(
        url,
        data=urlencode(form).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise EduzzAPIError(f"Eduzz OAuth HTTP {exc.code}: {detail}") from exc
    except (OSError, ValueError) as exc:
        raise EduzzAPIError(f"Falha na conexao OAuth Eduzz: {exc}") from exc


def exchange_code(code: str, state: str):
    if not code or not state or not db.consume_oauth_state(state):
        raise EduzzAPIError("Estado OAuth invalido ou expirado.")
    cfg = _config()
    token = _form_request(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"],
        "code": code,
    })
    if not token.get("access_token"):
        raise EduzzAPIError("A Eduzz nao retornou access_token.")
    _save_token(token)
    return connection_status()


def _refresh_token(token: dict) -> dict:
    cfg = _config()
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise EduzzAPIError("Refresh token da Eduzz ausente; reconecte o aplicativo.")
    refreshed = _form_request(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": refresh_token,
    })
    if not refreshed.get("refresh_token"):
        refreshed["refresh_token"] = refresh_token
    if not refreshed.get("access_token"):
        raise EduzzAPIError("A Eduzz nao renovou o access_token.")
    _save_token(refreshed)
    return refreshed


def _access_token() -> str:
    token = _load_token()
    if not token or not token.get("access_token"):
        raise EduzzAPIError("Aplicativo Eduzz ainda nao conectado.")
    if int(token.get("expires_at") or 0) <= int(time.time()) + 60:
        token = _refresh_token(token)
    return token["access_token"]


def request_json(path: str, params: dict = None) -> dict:
    url = f"{API_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_access_token()}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise EduzzAPIError(f"Eduzz API HTTP {exc.code}: {detail}") from exc
    except (OSError, ValueError) as exc:
        raise EduzzAPIError(f"Falha na API Eduzz: {exc}") from exc


def _records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "subscriptions"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _records(value)
            if nested:
                return nested
    return []


def _subscription_product_ids(item: dict) -> set:
    ids = set()
    product = item.get("product") or {}
    if isinstance(product, dict):
        ids.add(str(product.get("id") or product.get("productId") or ""))
    for product in item.get("products", []) or []:
        if isinstance(product, dict):
            ids.add(str(product.get("id") or product.get("productId") or ""))
    for key in ("productId", "product_id"):
        ids.add(str(item.get(key) or ""))
    return {value for value in ids if value}


def _buyer(item: dict) -> dict:
    source = (
        item.get("buyer")
        or item.get("customer")
        or item.get("payer")
        or item.get("client")
        or {}
    )
    return {
        "id": str(source.get("id") or source.get("customerId") or ""),
        "name": source.get("name") or "",
        "email": (source.get("email") or "").strip().lower(),
    }


def _timestamp(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).timestamp())
    except (TypeError, ValueError):
        return None


def reconcile_subscriptions() -> dict:
    """
    Reconcile clearly classified subscription records.

    Unknown record shapes/statuses are reported and left untouched, preventing
    accidental access revocation if the Eduzz schema changes.
    """
    product_filter = {
        value.strip()
        for value in os.environ.get("EDUZZ_PRODUCT_IDS", "").split(",")
        if value.strip()
    }
    response = request_json("/myeduzz/v1/subscriptions", {"page": 1})
    records = _records(response)
    result = {
        "records": len(records),
        "matched": 0,
        "activated": 0,
        "suspended": 0,
        "skipped": 0,
    }
    active_statuses = {"uptodate", "trial", "trialing", "free", "active"}
    inactive_statuses = {"late", "canceled", "cancelled", "finished", "expired"}

    for item in records:
        if not isinstance(item, dict):
            result["skipped"] += 1
            continue
        item_products = _subscription_product_ids(item)
        if product_filter and not (item_products & product_filter):
            result["skipped"] += 1
            continue
        buyer = _buyer(item)
        status = "".join(
            char for char in str(item.get("status") or "").lower()
            if char.isalnum()
        )
        if not buyer["email"] or status not in active_statuses | inactive_statuses:
            result["skipped"] += 1
            continue
        result["matched"] += 1
        contract_id = str(item.get("id") or item.get("contractId") or "")
        if status in active_statuses:
            expires_at = (
                _timestamp(item.get("nextChargeDate"))
                or _timestamp(item.get("expirationDate"))
                or int(time.time()) + int(
                    os.environ.get("DEFAULT_ACCESS_DAYS", "32")
                ) * 86400
            )
            user_id = db.upsert_user_from_webhook(
                email=buyer["email"],
                name=buyer["name"],
                buyer_id=buyer["id"],
                contract_id=contract_id,
                plan=str(item.get("planName") or ""),
                status="active",
                expires_at=expires_at,
            )
            db.log_audit(user_id, "eduzz.reconcile_active", status)
            result["activated"] += 1
        else:
            user = db.get_user_by_email(buyer["email"])
            if user:
                db.set_user_status(user["id"], "suspended")
                db.log_audit(user["id"], "eduzz.reconcile_suspended", status)
                result["suspended"] += 1
            else:
                result["skipped"] += 1
    return result
