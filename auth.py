"""
Autenticação e gestão de sessão.

Decisões:
- Hash de senhas com PBKDF2-HMAC-SHA256 (stdlib `hashlib`), 240k iteracoes.
- Sessao ÚNICA por usuario: criar nova invalida a anterior.
- Tokens de sessao: 32 bytes URL-safe.
- Cookie HttpOnly, Secure (em prod), SameSite=Lax.
- Sessao expira em SESSION_DAYS dias de inatividade.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time

import db

PBKDF2_ITER = 240_000
SESSION_DAYS = 14
SESSION_COOKIE = "udash_session"


def hash_password(password: str) -> str:
    """Gera hash no formato 'pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>'."""
    if not password or len(password) < 6:
        raise ValueError("A senha precisa ter pelo menos 6 caracteres.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Confere senha contra hash armazenado, em tempo constante."""
    if not password or not stored:
        return False
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iters = int(iters)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(hash_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expired(last_seen: int) -> bool:
    return (time.time() - last_seen) > (SESSION_DAYS * 86400)


def user_is_active(user_row) -> bool:
    """Aceita acesso apenas se status=active e nao expirou."""
    if not user_row:
        return False
    if user_row["status"] != "active":
        return False
    expires_at = user_row["expires_at"]
    if expires_at and time.time() > expires_at:
        return False
    return True


def make_set_cookie(token: str) -> str:
    secure = "Secure; " if os.environ.get("APP_PUBLIC_URL", "").startswith("https://") else ""
    return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; {secure}SameSite=Lax"


def make_clear_cookie() -> str:
    secure = "Secure; " if os.environ.get("APP_PUBLIC_URL", "").startswith("https://") else ""
    return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; {secure}SameSite=Lax"


ADMIN_COOKIE = "udash_admin"
DEMO_COOKIE = "udash_demo"
DEMO_MAX_AGE_SECONDS = 60 * 60 * 8


def _secure_cookie_prefix() -> str:
    return "Secure; " if os.environ.get("APP_PUBLIC_URL", "").startswith("https://") else ""


def _demo_cookie_secret() -> bytes:
    """Returns the server-only key used to sign the transient demo selector.

    The selector never carries credentials or cached data.  Reusing the internal
    service secret is deliberate backwards compatibility for existing Render
    deployments; a dedicated DASH_DEMO_COOKIE_SECRET can be configured later.
    """
    value = (
        os.environ.get("DASH_DEMO_COOKIE_SECRET")
        or os.environ.get("DASH_ADS_INTERNAL_SECRET")
        or os.environ.get("COMPETITIVE_WORKER_SECRET")
        or ""
    ).strip()
    if not value:
        raise RuntimeError("Modo Demo indisponivel: segredo de assinatura nao configurado.")
    return value.encode("utf-8")


def make_demo_set_cookie(account_id: int) -> str:
    issued_at = int(time.time())
    nonce = secrets.token_urlsafe(12)
    payload = f"{int(account_id)}:{issued_at}:{nonce}"
    signature = hmac.new(_demo_cookie_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    token = f"{encoded}.{signature}"
    return (
        f"{DEMO_COOKIE}={token}; Path=/; Max-Age={DEMO_MAX_AGE_SECONDS}; "
        f"HttpOnly; {_secure_cookie_prefix()}SameSite=Lax"
    )


def get_demo_context(token: str):
    """Validates a signed, short-lived demo selector without any database write."""
    if not token or "." not in token:
        return None
    encoded, supplied_signature = token.rsplit(".", 1)
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        expected_signature = hmac.new(
            _demo_cookie_secret(), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        account_id, issued_at, nonce = payload.split(":", 2)
        if not nonce or (time.time() - int(issued_at)) > DEMO_MAX_AGE_SECONDS:
            return None
        if int(account_id) <= 0:
            return None
        return {"account_id": int(account_id)}
    except (TypeError, ValueError, UnicodeDecodeError):
        return None


def make_demo_clear_cookie() -> str:
    return f"{DEMO_COOKIE}=; Path=/; Max-Age=0; HttpOnly; {_secure_cookie_prefix()}SameSite=Lax"


def make_admin_set_cookie(token: str) -> str:
    secure = "Secure; " if os.environ.get("APP_PUBLIC_URL", "").startswith("https://") else ""
    return f"{ADMIN_COOKIE}={token}; Path=/admin; Max-Age={SESSION_DAYS * 86400}; HttpOnly; {secure}SameSite=Lax"


def make_admin_clear_cookie() -> str:
    secure = "Secure; " if os.environ.get("APP_PUBLIC_URL", "").startswith("https://") else ""
    return f"{ADMIN_COOKIE}=; Path=/admin; Max-Age=0; HttpOnly; {secure}SameSite=Lax"


# Sessoes admin em memoria (poucos acessos, processo unico)
_admin_sessions = {}


def create_admin_session(email: str) -> str:
    token = secrets.token_urlsafe(32)
    _admin_sessions[token] = {"email": email, "created_at": time.time(), "last_seen": time.time()}
    return token


def get_admin_session(token: str):
    if not token:
        return None
    sess = _admin_sessions.get(token)
    if not sess:
        return None
    if (time.time() - sess["last_seen"]) > (SESSION_DAYS * 86400):
        _admin_sessions.pop(token, None)
        return None
    sess["last_seen"] = time.time()
    return sess


def destroy_admin_session(token: str):
    _admin_sessions.pop(token, None)
