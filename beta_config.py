"""Configuracao fail-closed do ambiente beta privado.

O beta pode usar contas reais autorizadas, mas nao compartilha sessoes,
cookies, banco, cache ou webhooks de cobranca com a producao.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BETA_MODE = _bool("BETA_MODE", False)
BETA_REJECT_BILLING_WEBHOOKS = _bool("BETA_REJECT_BILLING_WEBHOOKS", True)
BETA_SHARED_AUTH_URL = os.environ.get("BETA_SHARED_AUTH_URL", "").strip().rstrip("/")
BETA_SHARED_AUTH_SECRET = os.environ.get("BETA_SHARED_AUTH_SECRET", "").strip()
BETA_SHARED_ML_URL = os.environ.get("BETA_SHARED_ML_URL", "").strip().rstrip("/")
BETA_PUBLIC_URL = os.environ.get("BETA_PUBLIC_URL", "").strip().rstrip("/")
BETA_ALLOWED_EMAILS = frozenset(
    item.strip().lower()
    for item in os.environ.get("BETA_ALLOWED_EMAILS", "").split(",")
    if item.strip()
)


def route_enabled() -> bool:
    return BETA_MODE


def email_allowed(email: str) -> bool:
    return (BETA_MODE or bridge_enabled()) and (email or "").strip().lower() in BETA_ALLOWED_EMAILS


def shared_bridge_ready() -> bool:
    return bool(BETA_SHARED_AUTH_SECRET and BETA_SHARED_ML_URL)


def bridge_enabled() -> bool:
    return bool(BETA_SHARED_AUTH_SECRET and BETA_PUBLIC_URL)
