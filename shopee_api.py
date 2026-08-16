"""Cliente minimo Shopee Open Platform V2 para o piloto somente de leitura."""
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ShopeeAPIError(RuntimeError):
    pass


def _setting(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def is_configured() -> bool:
    return bool(_setting("SHOPEE_PARTNER_ID") and _setting("SHOPEE_PARTNER_KEY") and _setting("SHOPEE_TOKEN_ENCRYPTION_KEY"))


def callback_url() -> str:
    explicit = _setting("SHOPEE_OAUTH_CALLBACK_URL")
    if explicit:
        return explicit
    return _setting("APP_PUBLIC_URL").rstrip("/") + "/oauth/shopee/callback"


def _base_url() -> str:
    return _setting("SHOPEE_API_BASE_URL") or "https://partner.shopeemobile.com"


def _sign(path: str, timestamp: int) -> str:
    partner_id = _setting("SHOPEE_PARTNER_ID")
    key = _setting("SHOPEE_PARTNER_KEY")
    if not partner_id or not key:
        raise ShopeeAPIError("Credenciais Shopee de producao ainda nao foram configuradas.")
    raw = f"{partner_id}{path}{timestamp}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def authorization_url(state: str) -> str:
    if not is_configured():
        raise ShopeeAPIError("Configure SHOPEE_PARTNER_ID, SHOPEE_PARTNER_KEY e SHOPEE_TOKEN_ENCRYPTION_KEY antes de conectar uma loja.")
    path = "/api/v2/shop/auth_partner"
    timestamp = int(time.time())
    params = {
        "partner_id": _setting("SHOPEE_PARTNER_ID"),
        "timestamp": timestamp,
        "redirect": callback_url(),
        "sign": _sign(path, timestamp),
        "state": state,
    }
    return f"{_base_url().rstrip('/')}{path}?{urlencode(params)}"


def exchange_code(code: str, shop_id: int) -> dict:
    """Troca o code OAuth por tokens. Nunca registra nem devolve tokens ao HTML."""
    path = "/api/v2/auth/token/get"
    timestamp = int(time.time())
    body = json.dumps({
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": int(_setting("SHOPEE_PARTNER_ID")),
    }).encode("utf-8")
    request = Request(
        f"{_base_url().rstrip('/')}{path}?" + urlencode({
            "partner_id": _setting("SHOPEE_PARTNER_ID"),
            "timestamp": timestamp,
            "sign": _sign(path, timestamp),
        }),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(200_000).decode("utf-8"))
    except Exception as exc:
        raise ShopeeAPIError("Nao foi possivel concluir a autorizacao com a Shopee.") from exc
    if payload.get("error") or not payload.get("access_token"):
        raise ShopeeAPIError(payload.get("message") or payload.get("error") or "A Shopee nao retornou token de acesso.")
    return payload


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ShopeeAPIError("A dependencia de criptografia do conector Shopee nao esta instalada.") from exc
    raw_key = _setting("SHOPEE_TOKEN_ENCRYPTION_KEY")
    if not raw_key:
        raise ShopeeAPIError("SHOPEE_TOKEN_ENCRYPTION_KEY nao foi configurada.")
    try:
        # A variavel deve ser uma chave Fernet url-safe de 32 bytes.
        base64.urlsafe_b64decode(raw_key.encode("ascii"))
        return Fernet(raw_key.encode("ascii"))
    except Exception as exc:
        raise ShopeeAPIError("SHOPEE_TOKEN_ENCRYPTION_KEY invalida; gere uma chave Fernet nova.") from exc


def encrypt_token(value: str) -> str:
    return _fernet().encrypt((value or "").encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    return _fernet().decrypt((value or "").encode("ascii")).decode("utf-8")
