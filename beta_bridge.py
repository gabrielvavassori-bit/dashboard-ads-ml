"""Ponte de identidade entre producao e beta.

O assertion e curto, assinado e de uso unico. Ele carrega apenas identidade,
permissoes e metadados nao secretos do vinculo ML; nunca carrega cookie,
senha, access_token ou refresh_token.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time


TTL_SECONDS = 120


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def create_assertion(secret: str, user, ml_link, audience: str, now: int | None = None) -> str:
    if not secret:
        raise ValueError("ponte beta sem segredo")
    now = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "aud": audience,
        "iat": now,
        "exp": now + TTL_SECONDS,
        "nonce": secrets.token_urlsafe(18),
        "user": {
            "id": int(user["id"]),
            "email": (user["email"] or "").strip().lower(),
            "name": user["name"] or "",
            "plan": user["plan"] or "",
            "status": user["status"] or "",
            "expires_at": user["expires_at"],
        },
    }
    if ml_link:
        payload["ml"] = {
            key: (ml_link[key] or "")
            for key in (
                "client_id", "ml_user_id", "nickname", "official_store",
                "advertiser_id", "seller_id", "site_id", "status",
            )
            if key in ml_link.keys()
        }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(body, secret)}"


def verify_assertion(token: str, secret: str, audience: str, now: int | None = None) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = _sign(body, secret)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("assinatura invalida")
        payload = json.loads(_unb64(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeError, base64.binascii.Error) as exc:
        raise ValueError("assertion beta invalida") from exc
    now = int(time.time() if now is None else now)
    if payload.get("v") != 1 or payload.get("aud") != audience:
        raise ValueError("audiencia beta invalida")
    if not payload.get("nonce") or now >= int(payload.get("exp", 0)):
        raise ValueError("assertion beta expirada")
    if int(payload.get("iat", 0)) > now + 10:
        raise ValueError("assertion beta adiantada")
    user = payload.get("user") or {}
    if not user.get("id") or not user.get("email"):
        raise ValueError("identidade beta incompleta")
    return payload
