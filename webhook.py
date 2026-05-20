"""
Handler de webhooks da Eduzz (Webhook v3).

Documentacao oficial: https://developers.eduzz.com/docs/webhook
Configuracao: https://integrations.eduzz.com/webhook/configs

Eventos tratados:
- myeduzz.invoice_paid       -> ativa/renova acesso
- myeduzz.contract_created   -> ativa acesso (inicio de assinatura)
- myeduzz.contract_updated   -> ajusta acesso conforme contract.status
- myeduzz.invoice_refunded   -> revoga (refunded)
- myeduzz.invoice_canceled   -> revoga (canceled)
- myeduzz.invoice_expired    -> revoga (expired)

Assinatura: cabecalho 'x-signature' = HMAC-SHA256(secret, body).
"""
import hashlib
import hmac
import json
import os
import time

import db

# Lido de env var. Cadastre essa chave em "Chaves de acesso" no Orbita Eduzz
# e use a mesma na config do webhook.
EDUZZ_WEBHOOK_SECRET = os.environ.get("EDUZZ_WEBHOOK_SECRET", "")

# IDs dos produtos que sua oferta tem na Eduzz (separados por virgula).
# Se vazio, aceita qualquer produto (uso recomendado: preencher para evitar
# que outros webhooks da sua conta Eduzz interfiram aqui).
EDUZZ_PRODUCT_IDS = {
    pid.strip() for pid in os.environ.get("EDUZZ_PRODUCT_IDS", "").split(",") if pid.strip()
}

# Duracao padrao (em dias) ao receber pagamento sem informacao de proxima data.
DEFAULT_ACCESS_DAYS = int(os.environ.get("DEFAULT_ACCESS_DAYS", "32"))


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """HMAC-SHA256 em tempo constante. Tolera secret vazio rejeitando tudo."""
    if not EDUZZ_WEBHOOK_SECRET:
        return False
    if not signature_header:
        return False
    expected = hmac.new(
        EDUZZ_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    # x-signature pode vir como "sha256=xxx" ou apenas "xxx"
    sig = signature_header.strip()
    if "=" in sig:
        sig = sig.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, sig)


def _product_match(payload: dict) -> bool:
    """Se EDUZZ_PRODUCT_IDS estiver setado, processa so eventos desse produto."""
    if not EDUZZ_PRODUCT_IDS:
        return True
    data = payload.get("data", {}) or {}
    # 'product' aparece em invoice_* eventos, 'products' (array) em contract_*
    pid = ""
    if isinstance(data.get("product"), dict):
        pid = str(data["product"].get("id", ""))
    if pid in EDUZZ_PRODUCT_IDS:
        return True
    for prod in data.get("products", []) or []:
        if str(prod.get("id", "")) in EDUZZ_PRODUCT_IDS:
            return True
    # alguns payloads soltos podem ter productId/product_id na raiz dos dados
    for k in ("productId", "product_id"):
        if str(data.get(k, "")) in EDUZZ_PRODUCT_IDS:
            return True
    return False


def _extract_buyer(payload: dict):
    data = payload.get("data", {}) or {}
    buyer = data.get("buyer") or data.get("customer") or {}
    return {
        "id": str(buyer.get("id") or ""),
        "name": buyer.get("name") or "",
        "email": (buyer.get("email") or "").strip().lower(),
    }


def _extract_contract(payload: dict):
    data = payload.get("data", {}) or {}
    contract = data.get("contract") or {}
    return {
        "id": str(contract.get("id") or data.get("id") or ""),
        "status": (contract.get("status") or "").lower(),
    }


def _plan_name(payload: dict) -> str:
    data = payload.get("data", {}) or {}
    # contract_created/updated -> products[0].plan.name
    for prod in data.get("products", []) or []:
        plan = prod.get("plan") or {}
        if plan.get("name"):
            return plan["name"]
    # invoice_paid pode trazer offer.name
    offer = data.get("offer") or {}
    return offer.get("name") or ""


def _next_due_or_default(payload: dict) -> int:
    """
    Tenta extrair a proxima data de cobranca do payload (contract.nextChargeDate
    ou similar). Se nao achar, retorna agora + DEFAULT_ACCESS_DAYS.
    """
    data = payload.get("data", {}) or {}
    contract = data.get("contract") or {}
    # campos comuns na doc da Eduzz
    for key in ("nextChargeDate", "next_charge_date", "expirationDate", "expiration_date"):
        raw = contract.get(key) or data.get(key)
        if raw:
            try:
                # formato "2024-01-09T14:45:00.000Z"
                from datetime import datetime
                txt = str(raw).replace("Z", "+00:00")
                dt = datetime.fromisoformat(txt)
                return int(dt.timestamp())
            except Exception:
                pass
    return int(time.time()) + DEFAULT_ACCESS_DAYS * 86400


def process_event(raw_body: bytes, signature_header: str) -> dict:
    """
    Processa o corpo recebido. Retorna {'ok': bool, 'status': int, 'message': str}.
    Sempre devolve status na faixa 2xx para a Eduzz, exceto quando assinatura
    invalida ou body malformado (e ai pedimos retry com 4xx).
    """
    if not verify_signature(raw_body, signature_header):
        return {"ok": False, "status": 401, "message": "Assinatura invalida"}

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"ok": False, "status": 400, "message": "JSON invalido"}

    event_id = payload.get("id") or ""
    event_name = payload.get("event") or ""
    if not event_id or not event_name:
        return {"ok": False, "status": 400, "message": "Campos id/event ausentes"}

    # Idempotencia: se ja processamos esse event_id, devolvemos OK sem refazer.
    if db.webhook_event_seen(event_id):
        return {"ok": True, "status": 200, "message": "Evento ja processado"}

    db.webhook_event_save(event_id, event_name, raw_body.decode("utf-8", errors="replace"))

    # Filtro de produto (se configurado)
    if not _product_match(payload):
        return {"ok": True, "status": 200, "message": "Evento ignorado (produto fora do filtro)"}

    buyer = _extract_buyer(payload)
    contract = _extract_contract(payload)
    plan = _plan_name(payload)

    if not buyer["email"]:
        return {"ok": True, "status": 200, "message": "Sem email do comprador, evento ignorado"}

    # Mapeamento de eventos -> (status_user, expires_at)
    activate_events = {
        "myeduzz.invoice_paid",
        "myeduzz.contract_created",
    }
    revoke_events = {
        "myeduzz.invoice_refunded",
        "myeduzz.invoice_canceled",
        "myeduzz.invoice_expired",
        "myeduzz.invoice_waiting_refund",
    }

    if event_name in activate_events:
        expires_at = _next_due_or_default(payload)
        user_id = db.upsert_user_from_webhook(
            email=buyer["email"],
            name=buyer["name"],
            buyer_id=buyer["id"],
            contract_id=contract["id"],
            plan=plan,
            status="active",
            expires_at=expires_at,
        )
        db.log_audit(user_id, "webhook.activate", f"{event_name} plan={plan}")
        return {"ok": True, "status": 200, "message": f"Acesso ativado para {buyer['email']}"}

    if event_name == "myeduzz.contract_updated":
        # contract.status: upToDate | late | canceled | finished | trialing ...
        cstatus = contract["status"]
        if cstatus in ("uptodate", "trialing", "trial", "active"):
            expires_at = _next_due_or_default(payload)
            user_id = db.upsert_user_from_webhook(
                email=buyer["email"],
                name=buyer["name"],
                buyer_id=buyer["id"],
                contract_id=contract["id"],
                plan=plan,
                status="active",
                expires_at=expires_at,
            )
            db.log_audit(user_id, "webhook.contract_active", f"{cstatus}")
            return {"ok": True, "status": 200, "message": "Contrato em dia"}
        else:
            # late, canceled, finished, etc -> suspende. Quem voltar a pagar reativa via invoice_paid.
            user = db.get_user_by_email(buyer["email"])
            if user:
                db.set_user_status(user["id"], "suspended")
                db.log_audit(user["id"], "webhook.contract_suspended", f"{cstatus}")
            return {"ok": True, "status": 200, "message": f"Contrato {cstatus} - acesso suspenso"}

    if event_name in revoke_events:
        user = db.get_user_by_email(buyer["email"])
        if user:
            new_status = "refunded" if "refund" in event_name else "expired" if "expired" in event_name else "suspended"
            db.set_user_status(user["id"], new_status)
            db.log_audit(user["id"], f"webhook.{event_name}", new_status)
        return {"ok": True, "status": 200, "message": f"Acesso revogado ({event_name})"}

    # Evento valido mas que nao impacta acesso (ex: invoice_scheduled, invoice_waiting_payment)
    return {"ok": True, "status": 200, "message": f"Evento {event_name} registrado sem acao"}
