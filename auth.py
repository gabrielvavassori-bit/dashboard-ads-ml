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
