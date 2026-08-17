"""
Servidor principal do Dashboard ADS Mercado Livre (versao web).

Endpoints publicos:
  GET  /                -> tela de login OU painel se logado
  GET  /login           -> tela de login
  POST /login           -> processa login
  GET  /logout          -> destroi sessao e volta para login
  GET  /cadastrar       -> tela para criar senha (cliente recem-comprado)
  POST /cadastrar       -> processa cadastro de senha
  POST /gerar           -> recebe os 2 xlsx e devolve o dashboard HTML
  GET  /healthz         -> healthcheck para o Render/Railway
  POST /webhook/eduzz   -> recebe eventos da Eduzz
  GET/POST /eduzz/custom-delivery -> validacao de entrega customizada Eduzz

Endpoints admin:
  GET  /admin           -> lista clientes
  GET  /admin/login     -> login admin
  POST /admin/login     -> processa
  GET  /admin/logout    -> sair
  POST /admin/users/manual_access
  POST /admin/users/bind_ml_link
  POST /admin/users/<id>/reset_password
  POST /admin/users/<id>/grant_access
  POST /admin/users/<id>/set_status

Variaveis de ambiente:
  PORT                    Porta (padrao 4182)
  DATA_DIR                Pasta do banco SQLite (padrao ./data, em prod /var/data)
  APP_PUBLIC_URL          URL publica do app (ex: https://dashboard.unclic.com.br)
  EDUZZ_WEBHOOK_SECRET    Chave configurada na Eduzz para assinar webhooks
  EDUZZ_PRODUCT_IDS       IDs dos produtos validos, separados por virgula (opcional)
  EDUZZ_CLIENT_ID         Client ID do aplicativo OAuth Eduzz
  EDUZZ_CLIENT_SECRET     Client secret do aplicativo OAuth Eduzz
  EDUZZ_RECONCILE_SECRET  Segredo do endpoint interno de reconciliacao
  DEFAULT_ACCESS_DAYS     Dias de acesso quando o payload nao traz nextChargeDate
  ADMIN_EMAIL             Email do admin
  ADMIN_PASSWORD          Senha do admin (so usada no boot para criar/atualizar)
  GOVERNANCE_HUB_URL      URL do MARKETPLACE GOVERNANCE central
  GOVERNANCE_READ_API_KEY Chave de leitura do Governance central
  MAX_UPLOAD_MB           Limite por arquivo (padrao 20)
  SHOPEE_PARTNER_ID       Partner ID da Shopee Open Platform em producao
  SHOPEE_PARTNER_KEY      Partner key da Shopee Open Platform (somente cofre/ambiente)
  SHOPEE_TOKEN_ENCRYPTION_KEY Chave Fernet para tokens Shopee em repouso
"""
import html as _html
import calendar
import json
import os
import pathlib
import secrets
import tempfile
import traceback
import threading
import time
from datetime import date, datetime, timedelta
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import auth
import beta_bridge
import beta_config
import db
import eduzz_api
import shopee_api
import templates
import webhook as eduzz_webhook
from gerar_dashboard_ads_ml import (
    aggregate_by_campaign,
    aggregate_by_sku,
    apply_abc,
    apply_alerts,
    build_data,
    cvr_class,
    decision,
    mark_condition_context,
    mark_possible_catalog,
    render_dashboard,
)

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "4182"))
APP_VERSION = "Meli beta v6 - online"
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "https://dashboard-ads-ml.onrender.com")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# Limita 2 arquivos + overhead de multipart
MAX_BODY_BYTES = MAX_UPLOAD_BYTES * 2 + 1 * 1024 * 1024
AGENTE_ML_BASE_URL = os.environ.get("AGENTE_ML_BASE_URL", "https://agente-ml.onrender.com").rstrip("/")
GOVERNANCE_HUB_URL = os.environ.get(
    "GOVERNANCE_HUB_URL",
    "https://marketplace-governance-hub.onrender.com",
).rstrip("/")
ML_LINK_ATTACH_SECRET = (
    os.environ.get("ML_LINK_ATTACH_SECRET")
    or os.environ.get("DASH_ADS_INTERNAL_SECRET")
    or os.environ.get("COMPETITIVE_WORKER_SECRET", "")
).strip()
ONLINE_TZ = ZoneInfo("America/Sao_Paulo")
ONLINE_CACHE_PENDING_PREFIX = "__ONLINE_CACHE_PENDING__:"
SALES_INTELLIGENCE_HTML = pathlib.Path(__file__).resolve().parent / "assets" / "inteligencia-vendas-marketplace.html"

# Serializa geracoes pesadas para nao estourar memoria em planos pequenos.
# 2 dashboards em paralelo eh saudavel ate em 512MB-1GB RAM.
_dashboard_semaphore = threading.Semaphore(int(os.environ.get("MAX_PARALLEL_DASHBOARDS", "2")))


# ------------------ Helpers HTTP ------------------

def _client_ip(handler) -> str:
    return handler.headers.get("X-Forwarded-For", handler.client_address[0]).split(",")[0].strip()


def _get_cookies(handler) -> dict:
    raw = handler.headers.get("Cookie", "")
    if not raw:
        return {}
    c = SimpleCookie()
    try:
        c.load(raw)
    except Exception:
        return {}
    return {k: v.value for k, v in c.items()}


def _parse_form(handler):
    """Parse de application/x-www-form-urlencoded."""
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > 1_000_000:
        return {}
    body = handler.rfile.read(length).decode("utf-8", errors="replace")
    parsed = parse_qs(body, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def _parse_multipart(handler):
    """Le multipart/form-data respeitando MAX_BODY_BYTES."""
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        raise ValueError("Requisicao vazia.")
    if length > MAX_BODY_BYTES:
        raise ValueError(f"Arquivos muito grandes. Limite total: {MAX_BODY_BYTES // (1024*1024)} MB.")
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    files, fields = {}, {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if name and filename:
            data = part.get_payload(decode=True) or b""
            if len(data) > MAX_UPLOAD_BYTES:
                raise ValueError(f"O arquivo {filename!r} ultrapassa {MAX_UPLOAD_MB} MB.")
            files[name] = data
        elif name:
            fields[name] = part.get_payload(decode=True).decode("utf-8", errors="replace") if part.get_payload(decode=True) else ""
    return files, fields


def _send_html(handler, html: str, status: int = 200, set_cookie: str = None):
    data = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    if set_cookie:
        handler.send_header("Set-Cookie", set_cookie)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _redirect(handler, location: str, set_cookie: str = None, status: int = 302):
    handler.send_response(status)
    handler.send_header("Location", location)
    if set_cookie:
        handler.send_header("Set-Cookie", set_cookie)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _send_json(handler, payload: dict, status: int = 200):
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_and_discard_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > 0:
        handler.rfile.read(length)


def _absolute_app_url(path: str) -> str:
    return f"{APP_PUBLIC_URL.rstrip('/')}{path}"


def _fetch_dash_ads_json(path: str, params: dict | None = None) -> dict:
    secret = os.environ.get("DASH_ADS_INTERNAL_SECRET") or os.environ.get("COMPETITIVE_WORKER_SECRET", "")
    if not secret:
        return {"ok": False, "message": "Segredo interno do Dash ADS nao configurado."}
    query = urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = f"{AGENTE_ML_BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "X-COMPETITIVE-WORKER-SECRET": secret,
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=45) as response:
            raw = response.read(8_000_000)
            status = response.status
    except HTTPError as exc:
        raw = exc.read(8_000_000)
        status = exc.code
    except (URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "http_status": 502,
            "message": "Falha ao consultar agente-ml.",
            "error": exc.__class__.__name__,
        }
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        payload = {"ok": False, "message": "agente-ml retornou resposta nao JSON."}
    if isinstance(payload, dict):
        payload.pop("access_token", None)
        payload.pop("refresh_token", None)
        payload.pop("client_secret", None)
        payload.setdefault("http_status", status)
        payload.setdefault("token_exposed", False)
    return payload if isinstance(payload, dict) else {"ok": False, "payload": payload, "http_status": status}


def _fetch_governance_summary() -> tuple[dict, int]:
    api_key = (os.environ.get("GOVERNANCE_READ_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "error": "governance_read_api_key_not_configured"}, 503
    req = Request(
        f"{GOVERNANCE_HUB_URL}/v1/bundle",
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read(8_000_000)
            status = response.status
    except HTTPError as exc:
        raw = exc.read(8_000_000)
        status = exc.code
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": exc.__class__.__name__}, 502
    try:
        bundle = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "governance_non_json_response"}, 502
    if status != 200 or not isinstance(bundle, dict):
        return (bundle if isinstance(bundle, dict) else {"ok": False, "error": "invalid_bundle"}), status

    files = bundle.get("files") if isinstance(bundle.get("files"), dict) else {}
    active_rules = []
    for filename in ("global_rules.json", "shared_rules.json"):
        registry = files.get(filename) if isinstance(files.get(filename), dict) else {}
        for rule in registry.get("rules") or []:
            if not isinstance(rule, dict) or rule.get("active", True) is False:
                continue
            if str(rule.get("status") or "active").lower() in {"inactive", "disabled"}:
                continue
            active_rules.append(rule)
    decisions_registry = files.get("shared_human_decisions.json")
    decisions = (decisions_registry.get("decisions") or []) if isinstance(decisions_registry, dict) else []
    knowledge_registry = files.get("marketplace_knowledge.json")
    knowledge = (knowledge_registry.get("entries") or []) if isinstance(knowledge_registry, dict) else []
    selected_knowledge_ids = {
        "MK-AGML-ADS-RULE-CATALOG-INTAKE",
        "MK-AGML-SKU-CATALOG-OFFER-FALLBACK",
        "MK-ML-CATALOG-DEMAND-REQUIRES-INDIVIDUAL-AND-AGGREGATE-VIEW",
        "MK-ML-CONVERSION-PROXY-IS-LOWER-BOUND",
        "MK-ML-CATALOG-HEAT-USES-AGGREGATED-VISITS",
    }
    project_decisions = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        origin = " ".join(str(decision.get(key) or "") for key in ("source_project", "agent_of_origin")).lower()
        if "un clic" not in origin and "un-clic" not in origin and "unclic" not in origin:
            continue
        project_decisions.append({
            key: decision.get(key)
            for key in ("id", "description", "status", "classification")
        })
    return {
        "ok": True,
        "version": bundle.get("version"),
        "sha256": bundle.get("sha256"),
        "loaded_at": bundle.get("published_at"),
        "required_files": list(bundle.get("required_files") or []),
        "consulted_files": sorted(files.keys()),
        "central_rules_count": len(active_rules),
        "shared_human_decisions_count": len(decisions),
        "local_rules_checked": [],
        "conflicts": [],
        "affected_rules": [],
        "consulted_human_decisions": [],
        "blocked_count": 0,
        "altered_behavior_count": 0,
        "rule_catalog": [
            {"id": str(rule.get("id") or ""), "description": str(rule.get("description") or "")}
            for rule in active_rules if str(rule.get("id") or "").strip()
        ],
        "knowledge_catalog": [
            {"id": str(entry.get("id") or ""), "description": str(entry.get("description") or "")}
            for entry in knowledge
            if isinstance(entry, dict) and str(entry.get("id") or "").strip() in selected_knowledge_ids
        ],
        "project_decisions": project_decisions,
    }, 200


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _shift_month(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def _resolve_online_period(mode: str = "30d", month: str = "", date_from: str = "", date_to: str = "", compare: str = "none", now: datetime | None = None) -> dict:
    current = (now or datetime.now(ONLINE_TZ)).date()
    yesterday = current - timedelta(days=1)
    normalized = (mode or "30").strip().lower()
    aliases = {"7": "7d", "15": "15d", "30": "30d", "today": "today", "hoje": "today", "yesterday": "yesterday", "ontem": "yesterday", "month": "month", "mes": "month", "custom": "custom", "personalizado": "custom"}
    normalized = aliases.get(normalized, normalized)
    partial = False
    warning = ""
    error = ""
    if normalized == "today":
        start = end = current
        partial = True
        warning = "Hoje esta em andamento; os valores podem mudar ate o fechamento do dia."
        label = "Hoje"
    elif normalized == "yesterday":
        start = end = yesterday
        label = "Ontem"
    elif normalized in {"7d", "15d", "30d"}:
        days = int(normalized[:-1])
        start, end = current - timedelta(days=days), yesterday
        label = f"Ultimos {days} dias fechados"
    elif normalized == "month":
        selected = _parse_iso_date(f"{month}-01") if month else current.replace(day=1)
        if not selected:
            error = "Mes invalido."
            start = end = yesterday
            label = "Periodo invalido"
        else:
            start = selected.replace(day=1)
            end = selected.replace(day=calendar.monthrange(selected.year, selected.month)[1])
            if selected.year == current.year and selected.month == current.month and end >= current:
                end = yesterday
                partial = True
                warning = "O mes atual foi limitado ate ontem porque hoje ainda nao foi fechado."
            label = f"Mes {selected.year:04d}-{selected.month:02d}"
    elif normalized == "custom":
        start, end = _parse_iso_date(date_from), _parse_iso_date(date_to)
        label = "Personalizado"
        if not start or not end:
            error = "Informe data inicial e data final validas."
            start, end = yesterday, yesterday
        elif start > end:
            error = "A data inicial nao pode ser posterior a data final."
        elif end >= current:
            partial = True
            warning = "O periodo personalizado inclui hoje, que ainda esta em andamento."
    else:
        error = "Periodo invalido."
        normalized, start, end, label = "30d", current - timedelta(days=30), yesterday, "Ultimos 30 dias fechados"

    compare_mode = (compare or "none").strip().lower()
    if compare_mode not in {"none", "previous", "previous_month", "previous_year"}:
        compare_mode = "none"
    compare_period = None
    if not error and compare_mode != "none":
        if compare_mode == "previous":
            span = end - start
            compare_start, compare_end = start - span - timedelta(days=1), start - timedelta(days=1)
        elif compare_mode == "previous_month":
            compare_start = _shift_month(start, -1)
            compare_end = _shift_month(end, -1)
        else:
            try:
                compare_start, compare_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
            except ValueError:
                compare_start, compare_end = start.replace(year=start.year - 1, day=28), end.replace(year=end.year - 1, day=28)
        compare_period = {"dateFrom": compare_start.isoformat(), "dateTo": compare_end.isoformat(), "label": compare_mode}
    return {
        "mode": normalized,
        "month": month or "",
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "label": label,
        "partial": partial,
        "warning": warning,
        "compareMode": compare_mode,
        "comparePeriod": compare_period,
        "error": error,
    }


def _normalize_mlb_code(value) -> str:
    text_value = str(value or "").strip().upper()
    return text_value if text_value.startswith("MLB") else ""


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _deduplicate_online_ads_rows(ads_rows: list) -> tuple[list, dict]:
    deduped_rows = []
    seen = set()
    semantic_seen = {}
    removed_rows = 0
    removed_semantic_rows = 0
    removed_investment = 0.0
    removed_ads_revenue = 0.0

    for raw in ads_rows:
        if not isinstance(raw, dict):
            deduped_rows.append(raw)
            continue
        key = json.dumps(raw, sort_keys=True, ensure_ascii=True, default=str)
        if key in seen:
            removed_rows += 1
            removed_investment += _number(raw.get("cost"))
            removed_ads_revenue += _number(raw.get("total_amount"))
            continue
        seen.add(key)

        code = _normalize_mlb_code(raw.get("item_id") or raw.get("id"))
        campaign_id = str(raw.get("campaign_id") or "").strip()
        semantic_key = None
        if code and campaign_id:
            semantic_key = (
                code,
                campaign_id,
                str(raw.get("ad_group_id") or "").strip(),
                *(
                    _number(raw.get(field))
                    for field in (
                        "cost", "total_amount", "direct_amount", "units_quantity",
                        "direct_units_quantity", "indirect_units_quantity", "prints", "clicks",
                    )
                ),
            )
        if semantic_key in semantic_seen:
            existing_index = semantic_seen[semantic_key]
            existing = deduped_rows[existing_index]
            existing_status = str(existing.get("status") or "").strip().lower()
            current_status = str(raw.get("status") or "").strip().lower()
            existing_active = existing_status.startswith(("active", "ativo"))
            current_active = current_status.startswith(("active", "ativo"))
            if current_active and not existing_active:
                deduped_rows[existing_index] = raw
            removed_rows += 1
            removed_semantic_rows += 1
            removed_investment += _number(raw.get("cost"))
            removed_ads_revenue += _number(raw.get("total_amount"))
            continue
        if semantic_key is not None:
            semantic_seen[semantic_key] = len(deduped_rows)
        deduped_rows.append(raw)

    return deduped_rows, {
        "hasDuplicates": removed_rows > 0,
        "removedRows": removed_rows,
        "removedSemanticRows": removed_semantic_rows,
        "removedInvestment": removed_investment,
        "removedAdsRevenue": removed_ads_revenue,
    }


def _build_online_dashboard_data(client: str, advertiser_id: str = "", date_from: str = "", date_to: str = "", requested_period: dict | None = None) -> tuple[dict | None, str]:
    """Converte apenas o cache autenticado do agente em dados para o Dash ADS."""
    requested_at = datetime.now().astimezone().isoformat(timespec="seconds")
    requested_from = date_from or (requested_period or {}).get("dateFrom") or ""
    requested_to = date_to or (requested_period or {}).get("dateTo") or ""
    period_params = {"date_from": requested_from, "date_to": requested_to}
    latest_payload = _fetch_dash_ads_json(
        "/internal/dash-ads/online-cache-latest",
        {"client": client, "advertiser_id": advertiser_id, **period_params},
    )
    if not latest_payload.get("ok"):
        return None, "Nao foi possivel ler o snapshot online agora. A coleta segue em segundo plano; tente novamente em alguns minutos."

    latest = latest_payload.get("latest") if isinstance(latest_payload.get("latest"), dict) else {}
    ads = latest_payload.get("ads") if isinstance(latest_payload.get("ads"), dict) else {}
    sales = latest_payload.get("sales") if isinstance(latest_payload.get("sales"), dict) else {}
    latest_date_from = latest.get("date_from") or ads.get("date_from") or ""
    latest_date_to = latest.get("date_to") or ads.get("date_to") or ""
    period_cache_hit = latest_payload.get("period_cache_hit") is not False
    period_match = not (requested_from or requested_to) or (
        period_cache_hit
        and latest_date_from == requested_from
        and latest_date_to == requested_to
    )
    refresh_payload = {}
    if not period_match and requested_from and requested_to:
        refresh_payload = _fetch_dash_ads_json(
            "/internal/dash-ads/online-cache-refresh",
            {"client": client, "advertiser_id": advertiser_id, **period_params},
        )
        refreshed_payload = _fetch_dash_ads_json(
            "/internal/dash-ads/online-cache-latest",
            {"client": client, "advertiser_id": advertiser_id, **period_params},
        )
        if refreshed_payload.get("ok"):
            latest_payload = refreshed_payload
            period_cache_hit = refreshed_payload.get("period_cache_hit") is not False
            latest = refreshed_payload.get("latest") if isinstance(refreshed_payload.get("latest"), dict) else {}
            ads = refreshed_payload.get("ads") if isinstance(refreshed_payload.get("ads"), dict) else {}
            sales = refreshed_payload.get("sales") if isinstance(refreshed_payload.get("sales"), dict) else {}
    latest_date_from = latest.get("date_from") or ads.get("date_from") or ""
    latest_date_to = latest.get("date_to") or ads.get("date_to") or ""
    period_match = not (requested_from or requested_to) or (
        period_cache_hit
        and latest_date_from == requested_from
        and latest_date_to == requested_to
    )
    if not period_match:
        refresh_running = refresh_payload.get("ok") and refresh_payload.get("status") == "running"
        cached_status = latest_payload.get("status") if isinstance(latest_payload.get("status"), dict) else {}
        if refresh_running or cached_status.get("status") == "running":
            return None, (
                f"{ONLINE_CACHE_PENDING_PREFIX}Preparando os dados de {requested_from} a {requested_to}. "
                "A pagina sera atualizada automaticamente quando a coleta terminar."
            )
        return None, (
            f"Cache online fora do periodo selecionado ({latest_date_from or 'sem data'} a "
            f"{latest_date_to or 'sem data'}). Solicitado {requested_from or 'sem data'} a "
            f"{requested_to or 'sem data'}. Atualize a coleta online e tente novamente."
        )
    ads_rows = ads.get("items") if isinstance(ads.get("items"), list) else []
    sales_by_item = sales.get("items") if isinstance(sales.get("items"), dict) else {}
    if not ads_rows:
        return None, "Ainda nao existem dados de publicidade em cache para esta conta. Aguarde a coleta online e tente novamente."
    ads_rows, ads_deduplication = _deduplicate_online_ads_rows(ads_rows)
    daily_sales_rows, daily_sales_error = _sales_intelligence_fetch_daily_sales(
        client,
        latest_date_from,
        latest_date_to,
    )
    daily_sales_by_item: dict[str, list[dict]] = {}
    for daily_raw in daily_sales_rows:
        daily_code = _normalize_mlb_code(daily_raw.get("item_id") or daily_raw.get("id"))
        snapshot_date = str(daily_raw.get("snapshot_date") or daily_raw.get("date") or "").strip()
        if not daily_code or not snapshot_date:
            continue
        daily_sales_by_item.setdefault(daily_code, []).append({
            "date": snapshot_date,
            "orders": _number(daily_raw.get("orders_count")),
            "units": _number(daily_raw.get("units_total")),
            "revenue": _number(daily_raw.get("revenue_total")),
            "lastSaleDate": str(daily_raw.get("last_sale_date") or "").strip(),
            "lastSalePrice": _number(daily_raw.get("last_price")),
        })
    for daily_series in daily_sales_by_item.values():
        daily_series.sort(key=lambda row: row["date"])
    ads_codes = {
        _normalize_mlb_code(raw.get("item_id") or raw.get("id"))
        for raw in ads_rows
        if isinstance(raw, dict)
    }
    ads_codes.discard("")
    for code in sales_by_item:
        normalized_code = _normalize_mlb_code(code)
        if normalized_code and normalized_code not in ads_codes:
            ads_rows.append({"item_id": normalized_code})
            ads_codes.add(normalized_code)
    sales_state = latest.get("sales") if isinstance(latest.get("sales"), dict) else {}
    complete = bool(sales_state.get("complete"))

    items = []
    sales_codes_seen = set()
    for raw in ads_rows:
        if not isinstance(raw, dict):
            continue
        code = _normalize_mlb_code(raw.get("item_id") or raw.get("id"))
        if not code:
            continue
        sale = sales_by_item.get(code) if isinstance(sales_by_item.get(code), dict) else {}
        sale_sku = str(
            sale.get("sku") or sale.get("seller_sku") or sale.get("sellerSku") or ""
        ).strip()
        sale_title = str(
            sale.get("title") or sale.get("item_title") or sale.get("itemTitle") or ""
        ).strip()
        sale_last_date = str(
            sale.get("last_sale_date")
            or sale.get("lastSaleDate")
            or sale.get("last_sale_at")
            or sale.get("lastSaleAt")
            or ""
        ).strip()
        investment = _number(raw.get("cost"))
        ads_revenue = _number(raw.get("total_amount"))
        ads_direct_revenue = _number(raw.get("direct_amount"))
        ads_indirect_revenue = max(0.0, ads_revenue - ads_direct_revenue)
        sale_already_counted = code in sales_codes_seen
        sales_codes_seen.add(code)
        total_revenue = 0.0 if sale_already_counted else _number(sale.get("revenue_total"))
        orders = 0.0 if sale_already_counted else _number(sale.get("orders_count"))
        units = 0.0 if sale_already_counted else _number(sale.get("units_total"))
        ads_sales = _number(raw.get("units_quantity"))
        impressions = _number(raw.get("prints"))
        clicks = _number(raw.get("clicks"))
        organic_revenue = max(0.0, total_revenue - ads_direct_revenue)
        tacos_base = organic_revenue + ads_direct_revenue + ads_indirect_revenue
        campaign_id = str(raw.get("campaign_id") or "").strip()
        campaign_name = str(
            raw.get("campaign_name") or raw.get("campaign_title") or raw.get("campaign") or ""
        ).strip()
        campaign_label = campaign_name or (f"Campanha {campaign_id}" if campaign_id else "Sem campanha identificada")
        status = str(raw.get("status") or "").strip().lower()
        active = status.startswith("active") or status.startswith("ativo")
        campaign_status = (
            "Ativa"
            if active
            else ("Anuncio inativo na campanha" if status else "Status do anuncio nao informado")
        )
        current_price = _number(
            raw.get("price_effective")
            or raw.get("preco_efetivo")
            or raw.get("sale_price")
            or raw.get("price")
            or raw.get("current_price")
        )
        last_sale_price = _number(sale.get("last_price") or sale.get("lastPrice"))
        last_price = last_sale_price or current_price
        avg_sale_price = (total_revenue / units) if units else last_sale_price
        price_reference = last_sale_price or avg_sale_price
        price_change_pct = (
            ((current_price - price_reference) / price_reference)
            if current_price and price_reference
            else 0.0
        )
        suggested_test_price = 0.0
        pricing_signal = "dados_insuficientes"
        if current_price > price_reference > 0 and sale_last_date:
            suggested_test_price = round(price_reference + ((current_price - price_reference) * 0.60), 2)
            pricing_signal = "indicio_alta_preco_com_interrupcao"
        shipping = raw.get("shipping") if isinstance(raw.get("shipping"), dict) else {}
        free_shipping = raw.get("free_shipping") if "free_shipping" in raw else shipping.get("free_shipping")
        fast_shipping = raw.get("fast_shipping")
        if fast_shipping is None:
            fast_shipping = raw.get("fastShipping")
        if fast_shipping is None:
            fast_shipping = shipping.get("fast_shipping")
        if fast_shipping is None:
            fast_shipping = shipping.get("is_fast")
        item = {
            "sku": str(raw.get("sku") or "").strip() or sale_sku,
            "code": code,
            "title": str(raw.get("title") or "").strip() or sale_title,
            "lastSaleDate": sale_last_date,
            "lastSaleSort": 0,
            "lastPrice": last_price,
            "lastSalePrice": last_sale_price,
            "currentPrice": current_price,
            "avgSalePrice": avg_sale_price,
            "priceReference": price_reference,
            "priceChangePct": price_change_pct,
            "suggestedTestPrice": suggested_test_price,
            "pricingSignal": pricing_signal,
            "dailySeries": daily_sales_by_item.get(code, []),
            "listingTypeId": str(raw.get("listing_type_id") or raw.get("listingTypeId") or "").strip(),
            "logisticType": str(raw.get("logistic_type") or shipping.get("logistic_type") or "").strip(),
            "freeShipping": bool(free_shipping) if free_shipping is not None else None,
            "fastShipping": bool(fast_shipping) if fast_shipping is not None else None,
            "shippingCost": _number(
                raw.get("shipping_cost")
                or raw.get("estimated_shipping_cost")
                or shipping.get("cost")
            ),
            "promotionEligibility": "nao_consultada_no_cache_atual",
            "orders": orders,
            "units": units,
            "productRevenue": total_revenue,
            "indirectRevenue": ads_indirect_revenue,
            "totalRevenue": total_revenue,
            "investment": investment,
            "adsRevenue": ads_revenue,
            "adsDirectRevenue": ads_direct_revenue,
            "adsIndirectRevenue": ads_indirect_revenue,
            "organicRevenue": organic_revenue,
            "tacosBaseRevenue": tacos_base,
            "revenueOutsideAds": organic_revenue,
            "adsDependencyRatio": (ads_direct_revenue / total_revenue) if total_revenue else 0.0,
            "outsideAdsRatio": (organic_revenue / total_revenue) if total_revenue else 0.0,
            "adsAttributedRatio": (ads_revenue / total_revenue) if total_revenue else 0.0,
            "campaign": campaign_label,
            "campaignId": campaign_id,
            "campaignName": campaign_name,
            "adsCampaigns": f"Campanha {campaign_id}" if campaign_id else "",
            "campaignStatus": campaign_status,
            "userProductId": str(raw.get("user_product_id") or raw.get("userProductId") or "").strip(),
            "catalogProductId": str(raw.get("catalog_product_id") or raw.get("catalogProductId") or "").strip(),
            "catalogListing": bool(raw.get("catalog_listing") or raw.get("catalogListing")),
            "thumbnailUrl": str(
                raw.get("thumbnail_url")
                or raw.get("secure_thumbnail")
                or raw.get("thumbnail")
                or ""
            ).strip(),
            "impressions": impressions,
            "clicks": clicks,
            "adsSales": ads_sales,
            "ctr": (clicks / impressions) if impressions else 0.0,
            "cvr": (ads_sales / clicks) if clicks else 0.0,
            "cpc": (investment / clicks) if clicks else 0.0,
            "tacos": (investment / tacos_base) if tacos_base else 0.0,
            "roas": (ads_revenue / investment) if investment else 0.0,
            "avgAdsOrder": (ads_revenue / ads_sales) if ads_sales else last_price,
            "maxCpc": 0.0,
            "possibleCatalog": False,
            "salesCoverageComplete": complete,
        }
        item["maxCpc"] = item["avgAdsOrder"] * 0.03 * item["cvr"] if item["avgAdsOrder"] and item["cvr"] else 0.0
        item["cvrClass"] = cvr_class(item["cvr"] * 100)
        apply_alerts(item)
        item["action"], item["reason"] = decision(item)
        items.append(item)

    if not items:
        return None, "O cache online nao trouxe anuncios validos para esta conta."
    mark_possible_catalog(items)
    mark_condition_context(items)
    for item in items:
        apply_alerts(item)
        item["action"], item["reason"] = decision(item)
    sku_ads = aggregate_by_sku(items)
    campaign_ads = aggregate_by_campaign(items)
    apply_abc(items, "totalRevenue", "abcCode")
    apply_abc(sku_ads, "totalRevenue", "abcSku")
    apply_abc(campaign_ads, "totalRevenue", "abcCampaign")
    sku_abc = {item["sku"]: item["abcSku"] for item in sku_ads}
    for item in items:
        item["abcSku"] = sku_abc.get(item.get("sku") or "(sem SKU)", "C")

    total_revenue = sum(item["totalRevenue"] for item in items)
    total_investment = sum(item["investment"] for item in items)
    total_ads_revenue = sum(item["adsRevenue"] for item in items)
    total_ads_direct = sum(item["adsDirectRevenue"] for item in items)
    total_organic = max(0.0, total_revenue - total_ads_direct)
    total_tacos_base = total_revenue
    total_clicks = sum(item["clicks"] for item in items)
    total_ads_sales = sum(item["adsSales"] for item in items)
    snapshot_at = str(latest.get("updated_at") or ads.get("updated_at") or "").strip()
    snapshot_age_seconds = None
    try:
        snapshot_dt = datetime.fromisoformat(snapshot_at.replace("Z", "+00:00"))
        requested_dt = datetime.fromisoformat(requested_at)
        if snapshot_dt.tzinfo is None:
            snapshot_dt = snapshot_dt.replace(tzinfo=requested_dt.tzinfo)
        snapshot_age_seconds = max(0, int((requested_dt - snapshot_dt).total_seconds()))
    except (TypeError, ValueError):
        pass
    snapshot_meta = {
        "requestedAt": requested_at,
        "snapshotAt": snapshot_at,
        "snapshotAgeSeconds": snapshot_age_seconds,
        "snapshotSource": "agente-ml / online-cache-latest",
        "snapshotCadence": "diario as 06:00 (America/Sao_Paulo) + atualizacao sob demanda",
    }
    cache_status = "completo" if complete else "parcial"
    notice = (
        f"Modo online beta: leitura autenticada do faturamento bruto do cache da conta. A cobertura de vendas esta {cache_status}; "
        "confira pelo XLSX detalhado antes de qualquer decisao financeira definitiva."
    )
    if ads_deduplication["hasDuplicates"]:
        notice += (
            f" Foram removidas {ads_deduplication['removedRows']} linhas duplicadas do cache de Ads "
            "antes dos calculos."
        )
    return {
        "kpis": {
            "clientName": client,
            "salesSource": "online-cache-gross",
            "products": len(items),
            "units": sum(item["units"] for item in items),
            "revenue": total_revenue,
            "adsRevenue": total_ads_revenue,
            "adsDirectRevenue": total_ads_direct,
            "organicRevenue": total_organic,
            "tacosBaseRevenue": total_tacos_base,
            "investment": total_investment,
            "investmentNoAdsSales": sum(item["investment"] for item in items if item["investment"] > 0 and item["adsRevenue"] <= 0),
            "cvr": total_ads_sales / total_clicks if total_clicks else 0.0,
            "tacos": total_investment / total_tacos_base if total_tacos_base else 0.0,
            "roas": total_ads_revenue / total_investment if total_investment else 0.0,
            "adsNoSales": len([item for item in items if item["investment"] > 0 and item["adsRevenue"] <= 0]),
            "adsOnlyNoTotalSales": len([item for item in items if item["investment"] > 0 and item["totalRevenue"] <= 0]),
            "tacosHigh": len([item for item in items if item["investment"] > 0 and item["tacos"] > 0.03]),
            "salesNoAds": len([item for item in items if item["units"] > 0 and item["investment"] == 0]),
        },
        "meta": {
            "period": {"dateFrom": latest_date_from, "dateTo": latest_date_to},
            "revenueSource": "agente-ml / online-cache-latest / pedidos brutos",
            "onlineMode": {"enabled": True, "notice": notice, "complete": complete, "updatedAt": snapshot_at, "onlinePeriod": requested_period or {}, "periodMatch": period_match, "snapshot": snapshot_meta},
            "adsDeduplication": ads_deduplication,
            "dailySales": {
                "source": "agente-ml / sales-daily",
                "available": not bool(daily_sales_error),
                "error": daily_sales_error,
            },
        },
        "items": sorted(items, key=lambda item: (-item["investment"], -item["totalRevenue"])),
        "decisionItems": [item for item in items if item.get("sku")],
        "adsNoSales": [item for item in items if item["investment"] > 0 and item["adsRevenue"] <= 0],
        "highTacos": [item for item in items if item["investment"] > 0 and item["tacos"] > 0.03],
        "salesNoAds": [item for item in items if item["units"] > 0 and item["investment"] == 0],
        "skuAds": sku_ads,
        "campaignAds": campaign_ads,
        "adsByProduct": [item for item in items if item.get("sku")],
        "finishedNoSku": [item for item in items if not item.get("sku")],
        "onlineBeta": {"enabled": True, "client": client, "latest": latest_payload, "summary": {"totalItems": len(items)}, "requestedPeriod": requested_period or {}, "apiPeriod": {"dateFrom": latest_date_from, "dateTo": latest_date_to}, "periodMatch": period_match, "snapshot": snapshot_meta},
    }, ""


def _build_online_beta_payload(data: dict, client: str, advertiser_id: str = "") -> dict:
    period = (data.get("meta") or {}).get("period") or {}
    date_from = period.get("dateFrom") or ""
    date_to = period.get("dateTo") or ""
    context = _fetch_dash_ads_json("/internal/dash-ads/ml-context", {"client": client})
    resolved_advertiser_id = advertiser_id or context.get("advertiser_id") or ""
    api_reconciliation = _fetch_dash_ads_json(
        "/internal/dash-ads/ads-api-reconciliacao",
        {
            "client": client,
            "advertiser_id": resolved_advertiser_id,
            "date_from": date_from,
            "date_to": date_to,
        },
    )
    latest = _fetch_dash_ads_json(
        "/internal/dash-ads/online-cache-latest",
        {"client": client, "advertiser_id": resolved_advertiser_id},
    )
    latest_period = (((latest.get("latest") or {}).get("date_from")) or latest.get("date_from") or "", ((latest.get("latest") or {}).get("date_to")) or latest.get("date_to") or "")
    period_match = bool(date_from and date_to and api_reconciliation.get("date_from") == date_from and api_reconciliation.get("date_to") == date_to)

    api_rows_raw = api_reconciliation.get("items") or []
    api_by_code = {}
    for raw in api_rows_raw:
        if not isinstance(raw, dict):
            continue
        code = _normalize_mlb_code(raw.get("item_id") or raw.get("id"))
        if not code:
            continue
        target = api_by_code.setdefault(code, {
            "code": code,
            "title": raw.get("title") or "",
            "campaignIds": set(),
            "totalAmount": 0.0,
            "directAmount": 0.0,
            "indirectAmount": 0.0,
            "cost": 0.0,
            "clicks": 0.0,
            "prints": 0.0,
            "units": 0.0,
            "directUnits": 0.0,
            "indirectUnits": 0.0,
            "ctr": 0.0,
            "cvr": 0.0,
            "roas": 0.0,
        })
        total_amount = float(raw.get("total_amount") or 0)
        direct_amount = float(raw.get("direct_amount") or 0)
        target["campaignIds"].add(str(raw.get("campaign_id") or "").strip())
        target["totalAmount"] += total_amount
        target["directAmount"] += direct_amount
        target["indirectAmount"] += max(0.0, total_amount - direct_amount)
        target["cost"] += float(raw.get("cost") or 0)
        target["clicks"] += float(raw.get("clicks") or 0)
        target["prints"] += float(raw.get("prints") or 0)
        target["units"] += float(raw.get("units_quantity") or 0)
        target["directUnits"] += float(raw.get("direct_units_quantity") or 0)
        target["indirectUnits"] += float(raw.get("indirect_units_quantity") or 0)
    for target in api_by_code.values():
        target["campaignIds"] = ", ".join(sorted(x for x in target["campaignIds"] if x))
        target["ctr"] = (target["clicks"] / target["prints"]) if target["prints"] else 0.0
        target["cvr"] = (target["units"] / target["clicks"]) if target["clicks"] else 0.0
        target["roas"] = (target["totalAmount"] / target["cost"]) if target["cost"] else 0.0

    compare_rows = []
    for item in data.get("items", []):
        code = _normalize_mlb_code(item.get("code"))
        if not code:
            continue
        api_item = api_by_code.get(code)
        xlsx_ads_revenue = float(item.get("adsRevenue") or 0)
        xlsx_investment = float(item.get("investment") or 0)
        xlsx_clicks = float(item.get("clicks") or 0)
        xlsx_direct = float(item.get("adsDirectRevenue") or 0)
        xlsx_indirect = float(item.get("adsIndirectRevenue") or 0)
        if api_item:
            api_ads_revenue = float(api_item.get("totalAmount") or 0)
            api_investment = float(api_item.get("cost") or 0)
            api_clicks = float(api_item.get("clicks") or 0)
            revenue_delta = api_ads_revenue - xlsx_ads_revenue
            investment_delta = api_investment - xlsx_investment
            clicks_delta = api_clicks - xlsx_clicks
            ok = abs(revenue_delta) <= 1.0 and abs(investment_delta) <= 1.0 and abs(clicks_delta) <= 1.0
        else:
            api_ads_revenue = 0.0
            api_investment = 0.0
            api_clicks = 0.0
            revenue_delta = 0.0 - xlsx_ads_revenue
            investment_delta = 0.0 - xlsx_investment
            clicks_delta = 0.0 - xlsx_clicks
            ok = False
        compare_rows.append({
            "code": code,
            "sku": item.get("sku") or "",
            "title": item.get("title") or "",
            "xlsxCampaign": item.get("campaign") or "",
            "apiCampaign": (api_item or {}).get("campaignIds", ""),
            "xlsxAdsRevenue": xlsx_ads_revenue,
            "apiAdsRevenue": api_ads_revenue,
            "xlsxDirectRevenue": xlsx_direct,
            "xlsxIndirectRevenue": xlsx_indirect,
            "apiDirectRevenue": float((api_item or {}).get("directAmount") or 0),
            "apiIndirectRevenue": float((api_item or {}).get("indirectAmount") or 0),
            "xlsxInvestment": xlsx_investment,
            "apiInvestment": api_investment,
            "xlsxClicks": xlsx_clicks,
            "apiClicks": api_clicks,
            "revenueDelta": revenue_delta,
            "investmentDelta": investment_delta,
            "clicksDelta": clicks_delta,
            "status": "OK" if ok else ("Sem retorno API" if not api_item else "Divergente"),
        })
    compare_rows.sort(key=lambda item: (0 if item["status"] != "OK" else 1, -abs(item["revenueDelta"]), item["code"]))

    return {
        "enabled": True,
        "client": client,
        "advertiserId": resolved_advertiser_id,
        "context": context,
        "apiReconciliation": api_reconciliation,
        "latest": latest,
        "xlsxPeriod": {"dateFrom": date_from, "dateTo": date_to},
        "apiPeriod": {"dateFrom": api_reconciliation.get("date_from") or "", "dateTo": api_reconciliation.get("date_to") or ""},
        "cachePeriod": {"dateFrom": latest_period[0], "dateTo": latest_period[1]},
        "periodMatch": period_match,
        "items": compare_rows,
        "summary": {
            "totalItems": len(compare_rows),
            "matchedItems": len([item for item in compare_rows if item["status"] == "OK"]),
            "divergentItems": len([item for item in compare_rows if item["status"] == "Divergente"]),
            "missingItems": len([item for item in compare_rows if item["status"] == "Sem retorno API"]),
        },
    }


def _current_user(handler):
    """Retorna (user_row, session_token) ou (None, None)."""
    cookies = _get_cookies(handler)
    token = cookies.get(auth.SESSION_COOKIE)
    if not token:
        return None, None
    sess = db.get_session(token)
    if not sess:
        return None, None
    if auth.session_expired(sess["last_seen"]):
        db.delete_session(token)
        return None, None
    if not auth.user_is_active(sess):
        return None, None
    db.touch_session(token)
    user = db.get_user_by_id(sess["user_id"])
    return user, token


def _current_ml_account(user, token):
    links = db.list_active_ml_links_for_user(user["id"])
    session = db.get_session(token) if token else None
    selected_id = session["selected_ml_account_id"] if session else None
    link = db.get_active_ml_link_for_user(user["id"], selected_id)
    return link, links, selected_id


def _safe_return_to(value: str, fallback: str = "/") -> str:
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    return value


def _current_admin(handler):
    cookies = _get_cookies(handler)
    token = cookies.get(auth.ADMIN_COOKIE)
    return auth.get_admin_session(token), token


def _beta_access_allowed(user) -> bool:
    if not user:
        return False
    beta_enabled = user["beta_enabled"] if "beta_enabled" in user.keys() else None
    if beta_enabled is not None:
        return bool(beta_enabled)
    return beta_config.email_allowed(user["email"])


def _sales_access_allowed(user) -> bool:
    if not user:
        return False
    if "sales_enabled" not in user.keys():
        return True
    value = user["sales_enabled"]
    if value is None:
        return True
    return bool(value)


def _render_sales_intelligence() -> str:
    if not SALES_INTELLIGENCE_HTML.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {SALES_INTELLIGENCE_HTML}")
    return SALES_INTELLIGENCE_HTML.read_text(encoding="utf-8", errors="replace")


def _sales_intelligence_default_period(now: datetime | None = None) -> dict:
    current = (now or datetime.now(ONLINE_TZ)).date()
    yesterday = current - timedelta(days=1)
    start = current - timedelta(days=119)
    return {
        "mode": "bootstrap",
        "dateFrom": start.isoformat(),
        "dateTo": yesterday.isoformat(),
        "label": "Ultimos 120 dias fechados",
    }


def _sales_intelligence_parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _sales_intelligence_fetch_latest(client: str, advertiser_id: str, date_from: str, date_to: str) -> tuple[dict | None, str]:
    params = {"client": client, "advertiser_id": advertiser_id, "date_from": date_from, "date_to": date_to}
    latest_payload = _fetch_dash_ads_json("/internal/dash-ads/online-cache-latest", params)
    if not latest_payload.get("ok"):
        return None, "Nao foi possivel ler o cache online desta conta agora."
    latest = latest_payload.get("latest") if isinstance(latest_payload.get("latest"), dict) else {}
    ads = latest_payload.get("ads") if isinstance(latest_payload.get("ads"), dict) else {}
    latest_from = str(latest.get("date_from") or ads.get("date_from") or "").strip()
    latest_to = str(latest.get("date_to") or ads.get("date_to") or "").strip()
    if latest_from == date_from and latest_to == date_to:
        return latest_payload, ""

    refresh_payload = _fetch_dash_ads_json("/internal/dash-ads/online-cache-refresh", params)
    refreshed_payload = _fetch_dash_ads_json("/internal/dash-ads/online-cache-latest", params)
    if refreshed_payload.get("ok"):
        latest_payload = refreshed_payload
        latest = refreshed_payload.get("latest") if isinstance(refreshed_payload.get("latest"), dict) else {}
        ads = refreshed_payload.get("ads") if isinstance(refreshed_payload.get("ads"), dict) else {}
        latest_from = str(latest.get("date_from") or ads.get("date_from") or "").strip()
        latest_to = str(latest.get("date_to") or ads.get("date_to") or "").strip()
    if latest_from == date_from and latest_to == date_to:
        return latest_payload, ""
    if refresh_payload.get("ok") and refresh_payload.get("status") == "running":
        return None, (
            f"{ONLINE_CACHE_PENDING_PREFIX}Preparando os dados de {date_from} a {date_to}. "
            "A pagina sera atualizada automaticamente quando a coleta terminar."
        )
    return None, (
        f"Cache online fora do periodo solicitado ({latest_from or 'sem data'} a {latest_to or 'sem data'}). "
        "Tente novamente em alguns minutos."
    )


def _sales_intelligence_collect_item_meta(latest_payload: dict) -> dict[str, dict]:
    sales = latest_payload.get("sales") if isinstance(latest_payload.get("sales"), dict) else {}
    sales_items = sales.get("items") if isinstance(sales.get("items"), dict) else {}
    ads = latest_payload.get("ads") if isinstance(latest_payload.get("ads"), dict) else {}
    ads_rows = ads.get("items") if isinstance(ads.get("items"), list) else []
    meta: dict[str, dict] = {}
    for raw_code, raw_sale in sales_items.items():
        code = _normalize_mlb_code(raw_code)
        sale = raw_sale if isinstance(raw_sale, dict) else {}
        if not code:
            continue
        if _number(sale.get("units_total")) <= 0 and _number(sale.get("revenue_total")) <= 0:
            continue
        meta[code] = {
            "code": code,
            "sku": str(sale.get("sku") or sale.get("seller_sku") or sale.get("sellerSku") or "").strip(),
            "title": str(sale.get("title") or sale.get("item_title") or sale.get("itemTitle") or "").strip(),
        }
    for raw in ads_rows:
        if not isinstance(raw, dict):
            continue
        code = _normalize_mlb_code(raw.get("item_id") or raw.get("id"))
        if not code or code not in meta:
            continue
        if not meta[code]["sku"]:
            meta[code]["sku"] = str(raw.get("sku") or "").strip()
        if not meta[code]["title"]:
            meta[code]["title"] = str(raw.get("title") or "").strip()
    return meta


def _sales_intelligence_chunk_item_ids(item_ids: list[str], max_items: int = 60, max_chars: int = 2500) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for item_id in item_ids:
        extra = len(item_id) + (1 if current else 0)
        if current and (len(current) >= max_items or current_size + extra > max_chars):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(item_id)
        current_size += extra
    if current:
        chunks.append(current)
    return chunks


def _sales_intelligence_fetch_orders(client: str, item_ids: list[str], date_from: str, date_to: str) -> tuple[dict[str, dict], list[str]]:
    collected: dict[str, dict] = {}
    errors: list[str] = []
    for chunk in _sales_intelligence_chunk_item_ids(item_ids):
        payload = _fetch_dash_ads_json(
            "/vendas-items-detalhado",
            {
                "client": client,
                "date_from": date_from,
                "date_to": date_to,
                "items": ",".join(chunk),
            },
        )
        if isinstance(payload.get("items"), list):
            for raw in payload["items"]:
                if not isinstance(raw, dict):
                    continue
                code = _normalize_mlb_code(raw.get("item_id"))
                if code:
                    collected[code] = raw
            continue
        errors.append(str(payload.get("erro") or payload.get("message") or "falha ao consultar pedidos"))
    return collected, errors


def _sales_intelligence_fetch_daily_sales(client: str, date_from: str, date_to: str) -> tuple[list[dict], str]:
    payload = _fetch_dash_ads_json(
        "/internal/dash-ads/sales-daily",
        {
            "client": client,
            "date_from": date_from,
            "date_to": date_to,
        },
    )
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    if payload.get("ok") is True:
        return [row for row in rows if isinstance(row, dict)], ""
    return [], str(payload.get("erro") or payload.get("error") or "snapshots_diarios_indisponiveis")


def _build_sales_intelligence_memory_data(user, link) -> tuple[dict | None, str]:
    client_id = str(link["client_id"] or "").strip()
    if not client_id:
        return None, "Conta Mercado Livre vinculada sem client_id ativo."
    advertiser_id = str(link["advertiser_id"] or "").strip()
    period = _sales_intelligence_default_period()
    latest_payload, message = _sales_intelligence_fetch_latest(
        client_id,
        advertiser_id,
        period["dateFrom"],
        period["dateTo"],
    )
    if not latest_payload:
        return None, message

    item_meta = _sales_intelligence_collect_item_meta(latest_payload)
    daily_rows, daily_error = _sales_intelligence_fetch_daily_sales(
        client_id,
        period["dateFrom"],
        period["dateTo"],
    )
    if daily_error:
        return None, (
            "Nao foi possivel ler os snapshots diarios de vendas agora. "
            "A coleta continua em segundo plano; tente novamente em alguns minutos. "
            f"Detalhe tecnico: {daily_error}."
        )
    if not item_meta and not daily_rows:
        return {
            "clientName": link["official_store"] or link["nickname"] or client_id or (user["name"] or user["email"]),
            "pageSubtitle": "Leitura online beta da conta vinculada. Nenhuma venda encontrada na janela carregada.",
            "onlineNotice": "Base online sem vendas no periodo carregado. O upload manual continua disponivel para validacao historica.",
            "sales": [],
            "imports": [],
            "events": [],
            "reportWindow": "7d",
            "profitWindow": "30d",
            "globalSearchScope": "code",
            "globalSearch": "",
            "noSalesRejected": {},
        }, ""
    if not daily_rows and item_meta:
        return None, (
            "O cache agregado possui vendas, mas os snapshots diarios ainda nao estao disponiveis "
            "para esta janela. A coleta continua em segundo plano; tente novamente em alguns minutos."
        )
    sales_rows = []
    import_id = f"online:{client_id}:{period['dateFrom']}:{period['dateTo']}"
    row_number = 0
    for daily in daily_rows:
        code = _normalize_mlb_code(daily.get("item_id"))
        if not code:
            continue
        meta = item_meta.get(code) or {"sku": code, "title": ""}
        row_number += 1
        qty = max(0, int(_number(daily.get("units_total"))))
        orders_count = max(0, int(_number(daily.get("orders_count"))))
        gross = _number(daily.get("revenue_total"))
        unit_price = gross / qty if qty else 0
        snapshot_date = str(daily.get("snapshot_date") or "").strip()
        date_value = f"{snapshot_date}T12:00:00-03:00" if snapshot_date else ""
        month = snapshot_date[:7] if len(snapshot_date) >= 7 else ""
        sale_number = f"daily:{snapshot_date}:{code}"
        title = str(meta.get("title") or "").strip()
        sku = str(meta.get("sku") or code).strip()
        dedupe_parts = [sale_number, date_value, sku, code, str(qty), f"{unit_price:.2f}", f"{gross:.2f}"]
        sales_rows.append({
            "dedupeKey": "|".join(dedupe_parts),
            "importId": import_id,
            "fileName": f"OAuth Mercado Livre - {client_id}",
            "rowNumber": row_number,
            "client": link["official_store"] or link["nickname"] or client_id or (user["name"] or user["email"]),
            "channel": "Mercado Livre",
            "saleNumber": sale_number,
            "ordersCount": orders_count,
            "date": date_value,
            "month": month,
            "status": "paid",
            "statusDescription": "Venda online por OAuth/cache",
            "packageMulti": "",
            "isKit": "",
            "units": qty,
            "productRevenue": gross,
            "unitPrice": unit_price,
            "total": gross,
            "sellingFee": 0,
            "shippingRevenue": 0,
            "shippingFee": 0,
            "discounts": 0,
            "refunds": 0,
            "billingMonth": month,
            "adsSale": "",
            "sku": sku,
            "mlb": code,
            "title": title,
            "listingType": "",
            "deliveryMethod": "",
            "result": "",
            "destination": "",
            "resultReason": "",
            "complaintOpened": "",
            "complaintClosed": "",
            "mediation": "",
            "lineType": "item_sale",
            "eventClass": "venda",
            "promoClass": "indefinido",
        })
    sales_rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("saleNumber") or ""), str(row.get("mlb") or "")))
    total_units = sum(_number(row.get("units")) for row in sales_rows)
    total_revenue = sum(_number(row.get("productRevenue")) for row in sales_rows)
    imported_at = datetime.now(ONLINE_TZ).isoformat(timespec="seconds")
    client_label = link["official_store"] or link["nickname"] or client_id or (user["name"] or user["email"])
    online_notice = (
        f"Base online carregada via OAuth/cache para {client_label}. Cobertura inicial: {period['dateFrom']} ate {period['dateTo']}."
    )
    online_notice += " Fonte: snapshots diarios persistidos; a abertura da pagina nao refaz a busca de pedidos no Mercado Livre."
    return {
        "clientName": client_label,
        "pageSubtitle": "Leitura online beta da conta vinculada. O upload manual continua disponivel para validacao e historico completo.",
        "onlineNotice": online_notice,
        "sales": sales_rows,
        "imports": [{
            "importId": import_id,
            "fileName": f"OAuth Mercado Livre - {client_label}",
            "periodStart": period["dateFrom"],
            "periodEnd": period["dateTo"],
            "rows": len(sales_rows),
            "newRows": len(sales_rows),
            "duplicateRows": 0,
            "units": total_units,
            "revenue": total_revenue,
            "status": "Online / OAuth cache bruto",
            "importedAt": imported_at,
        }],
        "events": [],
        "reportWindow": "7d",
        "profitWindow": "30d",
        "globalSearchScope": "code",
        "globalSearch": "",
        "noSalesRejected": {},
    }, ""


def _inject_sales_intelligence_memory_data(html_text: str, payload: dict) -> str:
    snapshot = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    loader = f"""<script id="salesIntelligenceBootstrap" type="application/json">{snapshot}</script>
<script>
(function () {{
  function boot() {{
    try {{
      var node = document.getElementById('salesIntelligenceBootstrap');
      if (!node || !window.__marketplaceApp || !window.__marketplaceApp.setMemoryData) return false;
      var data = JSON.parse(node.textContent || '{{}}');
      var applyData = function () {{
        var clientInput = document.getElementById('clientName');
        if (clientInput && data.clientName) clientInput.value = data.clientName;
        var subtitle = document.getElementById('pageSubtitle');
        if (subtitle && data.pageSubtitle) subtitle.textContent = data.pageSubtitle;
        window.__marketplaceApp.setMemoryData(data);
      }};
      if (window.__marketplaceAppReady && typeof window.__marketplaceAppReady.then === 'function') {{
        window.__marketplaceAppReady.then(applyData);
      }} else {{
        applyData();
      }}
      return true;
    }} catch (err) {{
      console.error('Falha ao hidratar Inteligencia de Vendas online', err);
      return true;
    }}
  }}
  if (!boot()) {{
    var timer = setInterval(function () {{
      if (boot()) clearInterval(timer);
    }}, 120);
    setTimeout(function () {{ clearInterval(timer); }}, 8000);
  }}
}})();
</script>"""
    head, sep, tail = html_text.rpartition("</body>")
    if sep:
        return head + loader + "\n</body>" + tail
    return html_text + loader


def _sync_beta_access(user) -> bool:
    if beta_config.BETA_MODE:
        return True
    if not beta_config.bridge_enabled():
        return False
    audience = f"{beta_config.BETA_PUBLIC_URL}/internal/beta/access-sync"
    ml_accounts = db.list_active_ml_links_for_user(user["id"])
    legacy_ml_link = ml_accounts[0] if ml_accounts else None
    assertion = beta_bridge.create_assertion(
        beta_config.BETA_SHARED_AUTH_SECRET,
        user,
        legacy_ml_link,
        audience,
        ml_accounts=ml_accounts,
    )
    request = Request(
        audience,
        data=urlencode({"assertion": assertion}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(100_000).decode("utf-8", errors="replace"))
        return response.status == 200 and payload.get("ok") is True
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return False


def _sync_beta_user_if_enabled(user_id: int) -> bool:
    if beta_config.BETA_MODE:
        return True
    user = db.get_user_by_id(user_id)
    if not user or not bool(user["beta_enabled"]):
        return True
    return _sync_beta_access(user)


# ------------------ Handler ------------------

class Handler(BaseHTTPRequestHandler):
    # silencia o log padrao verboso
    def log_message(self, format, *args):  # noqa: A002
        return

    # ----------- GET -----------
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        try:
            if path == "/healthz":
                _send_json(self, {"ok": True})
                return
            if beta_config.BETA_MODE and (path == "/admin" or path.startswith("/admin/")):
                target = beta_config.BETA_SHARED_AUTH_URL.rstrip("/") + path
                if url.query:
                    target += "?" + url.query
                _redirect(self, target)
                return
            if path == "/api/governance/summary":
                user, _ = _current_user(self)
                if not user:
                    _send_json(self, {"ok": False, "error": "unauthorized"}, 401)
                    return
                payload, status = _fetch_governance_summary()
                _send_json(self, payload, status)
                return
            if path.startswith("/internal/dash-ads/"):
                self._internal_dash_ads_diagnostico(path, url)
                return
            if path in ("/eduzz/custom-delivery", "/eduzz-delivery"):
                self._eduzz_custom_delivery()
                return
            if path == "/login":
                user, _ = _current_user(self)
                if user:
                    _redirect(self, "/")
                    return
                qs = parse_qs(url.query or "")
                return_to = (qs.get("return_to", [""])[0] or "").strip()
                _send_html(self, templates.render_login(return_to=return_to))
                return
            if path == "/logout":
                _, token = _current_user(self)
                if token:
                    db.delete_session(token)
                _redirect(self, "/login", set_cookie=auth.make_clear_cookie())
                return
            if path == "/cadastrar":
                _send_html(self, templates.render_register())
                return
            if path == "/admin/login":
                _send_html(self, templates.render_admin_login())
                return
            if path == "/admin/logout":
                _, token = _current_admin(self)
                if token:
                    auth.destroy_admin_session(token)
                _redirect(self, "/admin/login", set_cookie=auth.make_admin_clear_cookie())
                return
            if path == "/admin/eduzz/connect":
                admin, _ = _current_admin(self)
                if not admin:
                    _redirect(self, "/admin/login")
                    return
                _redirect(self, eduzz_api.authorization_url())
                return
            if path == "/admin/eduzz/status":
                admin, _ = _current_admin(self)
                if not admin:
                    _send_json(self, {"ok": False, "message": "Nao autorizado"}, 401)
                    return
                _send_json(self, {"ok": True, **eduzz_api.connection_status()})
                return
            if path == "/oauth/eduzz/callback":
                self._eduzz_oauth_callback(url)
                return
            if path == "/shopee":
                user, _ = _current_user(self)
                if not user:
                    _redirect(self, "/login?return_to=/shopee")
                    return
                _send_html(self, templates.render_shopee_pilot(
                    user["name"] or user["email"],
                    db.list_active_shopee_accounts_for_user(user["id"]),
                    configured=shopee_api.is_configured(),
                    info=(parse_qs(url.query or "").get("info", [""])[0] or "")[:180],
                    error=(parse_qs(url.query or "").get("error", [""])[0] or "")[:180],
                ))
                return
            if path == "/shopee/link/start":
                self._shopee_link_start()
                return
            if path == "/oauth/shopee/callback":
                self._shopee_oauth_callback(url)
                return
            if path == "/beta/authorize":
                self._beta_authorize(url)
                return
            if path == "/beta/callback":
                self._beta_callback(url)
                return
            if path == "/admin" or path == "/admin/":
                admin, _ = _current_admin(self)
                if not admin:
                    _redirect(self, "/admin/login")
                    return
                qs = parse_qs(url.query or "")
                q = (qs.get("q", [""])[0] or "").strip()
                users = []
                for raw_user in db.list_users(q):
                    user = dict(raw_user)
                    links = db.list_active_ml_links_for_user(user["id"])
                    if links:
                        link = links[0]
                        user["ml_link_label"] = (
                            link["official_store"]
                            or link["nickname"]
                            or link["client_id"]
                            or ""
                        )
                        user["ml_link_count"] = len(links)
                        user["ml_link_detail"] = " | ".join(
                            part for part in [
                                link["client_id"] or "",
                                link["ml_user_id"] or "",
                                link["advertiser_id"] or "",
                            ] if part
                        )
                    else:
                        user["ml_link_label"] = ""
                        user["ml_link_detail"] = ""
                    users.append(user)
                info = (qs.get("info", [""])[0] or "")
                _send_html(self, templates.render_admin_users(users, q, info))
                return
            if path == "/":
                user, token = _current_user(self)
                if not user:
                    _redirect(self, "/login")
                    return
                if beta_config.BETA_MODE and not _beta_access_allowed(user):
                    _send_html(self, templates.render_error_page("Este usuario nao esta autorizado para o ambiente beta."), 403)
                    return
                link, links, _ = _current_ml_account(user, token)
                linked_name = ""
                if link:
                    linked_name = link["official_store"] or link["nickname"] or link["client_id"] or ""
                _send_html(
                    self,
                    templates.render_app_shell(
                        user["name"] or user["email"],
                        APP_VERSION,
                        linked_client_name=linked_name,
                        sales_enabled=_sales_access_allowed(user),
                        account_count=len(links),
                    ),
                )
                return
            if path == "/contas":
                user, token = _current_user(self)
                if not user:
                    _redirect(self, "/login?return_to=/contas")
                    return
                qs = parse_qs(url.query or "")
                return_to = _safe_return_to(qs.get("return_to", ["/"])[0], "/")
                _, links, selected_id = _current_ml_account(user, token)
                _send_html(self, templates.render_ml_account_selector(
                    user["name"] or user["email"], links, selected_id, return_to,
                    int(user["ml_slot_limit"] or 1),
                ))
                return
            if path in ("/inteligencia-vendas", "/inteligencia-vendas/"):
                user, token = _current_user(self)
                if not user:
                    _redirect(self, "/login?return_to=/inteligencia-vendas")
                    return
                if not _sales_access_allowed(user):
                    _send_html(self, templates.render_error_page("A Inteligencia de Vendas esta bloqueada para este cliente no painel admin."), 403)
                    return
                link, links, _ = _current_ml_account(user, token)
                if links and not link:
                    _redirect(self, "/contas?return_to=/inteligencia-vendas")
                    return
                html = _render_sales_intelligence()
                if link:
                    payload, message = _build_sales_intelligence_memory_data(user, link)
                    if payload:
                        html = _inject_sales_intelligence_memory_data(html, payload)
                    elif message.startswith(ONLINE_CACHE_PENDING_PREFIX):
                        _send_html(
                            self,
                            templates.render_online_cache_pending(
                                message[len(ONLINE_CACHE_PENDING_PREFIX):],
                            ),
                            202,
                        )
                        return
                _send_html(self, html)
                return
            if path == "/online":
                user, token = _current_user(self)
                if not user:
                    _redirect(self, "/login")
                    return
                if beta_config.BETA_MODE and not _beta_access_allowed(user):
                    _send_html(self, templates.render_error_page("Este usuario nao esta autorizado para o ambiente beta."), 403)
                    return
                qs = parse_qs(url.query or "")
                confirmed = (qs.get("confirmed", [""])[0] or "").strip() == "1"
                period = _resolve_online_period(
                    mode=qs.get("period", ["30d"])[0],
                    month=qs.get("month", [""])[0],
                    date_from=qs.get("date_from", [""])[0],
                    date_to=qs.get("date_to", [""])[0],
                    compare=qs.get("compare", ["none"])[0],
                )
                if period["error"]:
                    _send_html(self, templates.render_error_page(period["error"]), 400)
                    return
                link, links, selected_account_id = _current_ml_account(user, token)
                if links and not link:
                    _redirect(self, "/contas?" + urlencode({"return_to": self.path}))
                    return
                linked_name = ""
                if link:
                    linked_name = link["official_store"] or link["nickname"] or link["client_id"] or ""
                if not confirmed:
                    _send_html(self, templates.render_online_beta_warning(
                        linked_name,
                        account_count=len(links),
                        slot_limit=int(user["ml_slot_limit"] or 1),
                        accounts=links,
                        selected_account_id=selected_account_id or (link["id"] if link else None),
                    ))
                    return
                if not link:
                    _redirect(self, "/ml-link/start?return_to=/online?confirmed=1")
                    return
                client_id = (link["client_id"] or "").strip()
                if not client_id:
                    db.mark_user_ml_link_disconnected(user["id"], link["id"])
                    _redirect(self, "/ml-link/start?return_to=/online?confirmed=1")
                    return
                dashboard_data, message = _build_online_dashboard_data(
                    client_id,
                    advertiser_id=(link["advertiser_id"] or "").strip(),
                    date_from=period["dateFrom"],
                    date_to=period["dateTo"],
                    requested_period=period,
                )
                if not dashboard_data:
                    if message.startswith(ONLINE_CACHE_PENDING_PREFIX):
                        _send_html(
                            self,
                            templates.render_online_cache_pending(
                                message[len(ONLINE_CACHE_PENDING_PREFIX):],
                            ),
                            202,
                        )
                        return
                    _send_html(self, templates.render_error_page(message), 503)
                    return
                _send_html(self, render_dashboard(dashboard_data))
                return
            if path in ("/teste", "/teste/"):
                self._beta_entry()
                return
            if path == "/ml-link/start":
                user, _ = _current_user(self)
                if not user:
                    _redirect(self, "/login")
                    return
                qs = parse_qs(url.query or "")
                return_to = _safe_return_to(qs.get("return_to", ["/online"])[0], "/online")
                try:
                    slot_number = int(qs.get("slot", ["1"])[0] or 1)
                except ValueError:
                    _send_html(self, templates.render_error_page("Slot de conta invalido."), 400)
                    return
                if slot_number < 1 or slot_number > int(user["ml_slot_limit"] or 1):
                    _send_html(self, templates.render_error_page("Este slot ainda nao foi liberado pelo administrador."), 403)
                    return
                bridge_state = f"mlink-{secrets.token_hex(16)}"
                db.save_ml_link_state(
                    bridge_state, user["id"], return_to=return_to, slot_number=slot_number,
                )
                connect_url = (
                    f"{AGENTE_ML_BASE_URL}/conectar-conta?"
                    f"{urlencode({'bridge_state': bridge_state, 'return_to': _absolute_app_url('/ml-link/finish')})}"
                )
                _redirect(self, connect_url)
                return
            if path == "/ml-link/finish":
                user, token = _current_user(self)
                if not user:
                    _redirect(self, "/login")
                    return
                qs = parse_qs(url.query or "")
                bridge_state = (qs.get("state", [""])[0] or "").strip()
                if not bridge_state:
                    _redirect(self, "/?info=ativacao-invalida")
                    return
                state_row = db.consume_ml_link_state(bridge_state)
                if not state_row:
                    _send_html(self, templates.render_error_page("Nao consegui concluir a vinculacao da conta Mercado Livre."), 400)
                    return
                if state_row["user_id"] != user["id"]:
                    _send_html(self, templates.render_error_page("A vinculacao desta conta nao pertence a sua sessao atual."), 403)
                    return
                account = db.get_ml_account_by_slot(user["id"], state_row["slot_number"])
                if account:
                    db.set_session_selected_ml_account(token, user["id"], account["id"])
                _redirect(self, state_row["return_to"] or "/online")
                return

            _send_html(self, templates.render_error_page("Pagina nao encontrada."), 404)
        except Exception as exc:
            tb = traceback.format_exc()
            _send_html(self, templates.render_error_page(str(exc), tb), 500)

    def do_OPTIONS(self):
        url = urlparse(self.path)
        if url.path in ("/eduzz/custom-delivery", "/eduzz-delivery"):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ----------- POST -----------
    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        try:
            if path == "/login":
                self._post_login()
                return
            if path == "/cadastrar":
                self._post_register()
                return
            if path == "/gerar":
                self._post_gerar()
                return
            if path == "/webhook/eduzz":
                self._post_webhook()
                return
            if path == "/internal/eduzz/reconcile":
                self._post_eduzz_reconcile()
                return
            if path == "/internal/ml-link/attach":
                self._post_internal_ml_link_attach()
                return
            if path == "/internal/beta/access-sync":
                self._post_internal_beta_access_sync()
                return
            if beta_config.BETA_MODE and (path == "/admin" or path.startswith("/admin/")):
                _read_and_discard_body(self)
                _send_json(self, {"ok": False, "error": "Admin gerenciado no ambiente original."}, 403)
                return
            if path == "/contas/select":
                self._post_select_ml_account()
                return
            if path.endswith("/set_sales_access"):
                self._post_admin_set_sales_access(path)
                return
            if path in ("/eduzz/custom-delivery", "/eduzz-delivery"):
                self._eduzz_custom_delivery()
                return
            if path == "/admin/login":
                self._post_admin_login()
                return
            if path == "/admin/users/manual_access":
                self._post_admin_manual_access()
                return
            if path == "/admin/users/bind_ml_link":
                self._post_admin_bind_ml_link()
                return
            if path.startswith("/admin/users/") and path.endswith("/reset_password"):
                self._post_admin_reset_password(path)
                return
            if path.startswith("/admin/users/") and path.endswith("/grant_access"):
                self._post_admin_grant_access(path)
                return
            if path.startswith("/admin/users/") and path.endswith("/set_status"):
                self._post_admin_set_status(path)
                return
            if path.startswith("/admin/users/") and path.endswith("/set_beta_access"):
                self._post_admin_set_beta_access(path)
                return
            if path.startswith("/admin/users/") and path.endswith("/set_ml_slot_limit"):
                self._post_admin_set_ml_slot_limit(path)
                return

            _send_html(self, templates.render_error_page("Rota nao encontrada."), 404)
        except Exception as exc:
            tb = traceback.format_exc()
            _send_html(self, templates.render_error_page(str(exc), tb), 500)

    # ----------- Handlers especificos -----------

    def _shopee_link_start(self):
        """Inicia OAuth somente quando o ambiente de producao estiver pronto."""
        user, _ = _current_user(self)
        if not user:
            _redirect(self, "/login?return_to=/shopee")
            return
        if not shopee_api.is_configured():
            _redirect(self, "/shopee?error=" + quote("Go-Live ou configuracao segura ainda pendente."))
            return
        state = "shp-" + secrets.token_urlsafe(24)
        db.save_shopee_link_state(state, user["id"], return_to="/shopee")
        db.log_audit(user["id"], "shopee.oauth.start", "read_only", _client_ip(self))
        try:
            _redirect(self, shopee_api.authorization_url(state))
        except shopee_api.ShopeeAPIError as exc:
            _redirect(self, "/shopee?error=" + quote(str(exc)))

    def _shopee_oauth_callback(self, url):
        qs = parse_qs(url.query or "")
        state = (qs.get("state", [""])[0] or "").strip()
        code = (qs.get("code", [""])[0] or "").strip()
        shop_id = (qs.get("shop_id", [""])[0] or "").strip()
        if not state or not code or not shop_id:
            _send_html(self, templates.render_error_page("A Shopee nao retornou os dados necessarios para concluir a autorizacao."), 400)
            return
        link_state = db.consume_shopee_link_state(state)
        if not link_state:
            _send_html(self, templates.render_error_page("Esta autorizacao Shopee expirou, ja foi usada ou nao pertence a uma sessao valida."), 400)
            return
        try:
            token_payload = shopee_api.exchange_code(code, int(shop_id))
            access_encrypted = shopee_api.encrypt_token(token_payload.get("access_token", ""))
            refresh_encrypted = shopee_api.encrypt_token(token_payload.get("refresh_token", "")) if token_payload.get("refresh_token") else ""
            ts = int(time.time())
            expires_in = int(token_payload.get("expire_in", 0) or 0)
            refresh_expires_in = int(token_payload.get("refresh_token_expire_in", 0) or 0)
            db.upsert_shopee_account(
                link_state["user_id"], shop_id, access_encrypted, refresh_encrypted,
                token_expires_at=(ts + expires_in if expires_in else None),
                refresh_expires_at=(ts + refresh_expires_in if refresh_expires_in else None),
                region="BR",
            )
            db.log_audit(link_state["user_id"], "shopee.oauth.connected", f"shop_id={shop_id}", _client_ip(self))
            _redirect(self, "/shopee?info=" + quote("Loja Shopee vinculada em modo leitura."))
        except (ValueError, shopee_api.ShopeeAPIError):
            db.log_audit(link_state["user_id"], "shopee.oauth.failed", "token_exchange", _client_ip(self))
            _redirect(self, "/shopee?error=" + quote("Nao foi possivel concluir a vinculacao Shopee. Confira o Go-Live e tente novamente."))

    def _post_select_ml_account(self):
        user, token = _current_user(self)
        if not user:
            _redirect(self, "/login?return_to=/contas")
            return
        form = _parse_form(self)
        try:
            account_id = int((form.get("account_id", "") or "").strip())
        except ValueError:
            _send_html(self, templates.render_error_page("Conta Mercado Livre invalida."), 400)
            return
        if not db.set_session_selected_ml_account(token, user["id"], account_id):
            _send_html(self, templates.render_error_page("Esta conta nao pertence ao usuario autenticado."), 403)
            return
        db.log_audit(user["id"], "ml_account.select", str(account_id), _client_ip(self))
        _redirect(self, _safe_return_to(form.get("return_to", "/"), "/"))

    def _post_login(self):
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        password = form.get("password", "") or ""
        return_to = (form.get("return_to", "") or "").strip()
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/"
        if not email or not password:
            _send_html(self, templates.render_login("Informe email e senha.", email=email, return_to=return_to), 400)
            return
        user = db.get_user_by_email(email)
        if not user or not user["password_hash"] or not auth.verify_password(password, user["password_hash"]):
            db.log_audit(user["id"] if user else None, "login.fail", email, _client_ip(self))
            _send_html(self, templates.render_login("Email ou senha invalidos.", email=email, return_to=return_to), 401)
            return
        if not auth.user_is_active(user):
            db.log_audit(user["id"], "login.inactive", user["status"], _client_ip(self))
            _send_html(self, templates.render_login(
                "Sua assinatura nao esta ativa. Verifique seu pagamento na Eduzz ou fale com o suporte.", email=email, return_to=return_to
            ), 403)
            return
        token = auth.new_session_token()
        db.create_session(user["id"], token, _client_ip(self), self.headers.get("User-Agent", "")[:200])
        db.log_audit(user["id"], "login.ok", "", _client_ip(self))
        _redirect(self, return_to, set_cookie=auth.make_set_cookie(token))

    def _post_register(self):
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        password = form.get("password", "") or ""
        password2 = form.get("password2", "") or ""
        if not email or not password:
            _send_html(self, templates.render_register("Preencha todos os campos.", email=email), 400)
            return
        if password != password2:
            _send_html(self, templates.render_register("As senhas nao conferem.", email=email), 400)
            return
        if len(password) < 6:
            _send_html(self, templates.render_register("A senha precisa ter pelo menos 6 caracteres.", email=email), 400)
            return
        user = db.get_user_by_email(email)
        if not user:
            _send_html(self, templates.render_register(
                "Nao encontramos esse email. Use exatamente o mesmo email da sua compra na Eduzz.", email=email
            ), 404)
            return
        if not auth.user_is_active(user):
            _send_html(self, templates.render_register(
                "Sua assinatura nao esta ativa no momento. Verifique seu pagamento na Eduzz.", email=email
            ), 403)
            return
        if user["password_hash"]:
            _send_html(self, templates.render_register(
                "Ja existe uma senha cadastrada para esse email. Use a tela de login. "
                "Se voce esqueceu sua senha, fale com o suporte para resetar.", email=email
            ), 409)
            return
        try:
            pwd_hash = auth.hash_password(password)
        except ValueError as exc:
            _send_html(self, templates.render_register(str(exc), email=email), 400)
            return
        db.set_password(user["id"], pwd_hash)
        db.log_audit(user["id"], "register.ok", "", _client_ip(self))
        # ja loga o cliente
        token = auth.new_session_token()
        db.create_session(user["id"], token, _client_ip(self), self.headers.get("User-Agent", "")[:200])
        _redirect(self, "/", set_cookie=auth.make_set_cookie(token))

    def _post_gerar(self):
        user, _ = _current_user(self)
        if not user:
            _redirect(self, "/login")
            return
        try:
            files, fields = _parse_multipart(self)
        except ValueError as exc:
            link = db.get_active_ml_link_for_user(user["id"])
            linked_name = link["official_store"] or link["nickname"] or link["client_id"] if link else ""
            _send_html(
                self,
                templates.render_app_shell(
                    user["name"] or user["email"],
                    APP_VERSION,
                    str(exc),
                    linked_client_name=linked_name,
                    sales_enabled=_sales_access_allowed(user),
                ),
                400,
            )
            return
        if "sales" not in files or "ads" not in files:
            link = db.get_active_ml_link_for_user(user["id"])
            linked_name = link["official_store"] or link["nickname"] or link["client_id"] if link else ""
            _send_html(
                self,
                templates.render_app_shell(
                    user["name"] or user["email"],
                    APP_VERSION,
                    "Envie os dois arquivos: planilha de vendas e relatorio de publicidade.",
                    linked_client_name=linked_name,
                    sales_enabled=_sales_access_allowed(user),
                ),
                400,
            )
            return
        # Serializa por seguranca de memoria
        with _dashboard_semaphore:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = pathlib.Path(tmp)
                sales_path = tmp_path / "vendas.xlsx"
                ads_path = tmp_path / "ads.xlsx"
                sales_path.write_bytes(files["sales"])
                ads_path.write_bytes(files["ads"])
                try:
                    dashboard_data = build_data(sales_path, ads_path)
                    link = db.get_active_ml_link_for_user(user["id"])
                    if link and (link["client_id"] or "").strip():
                        dashboard_data["onlineBeta"] = _build_online_beta_payload(
                            dashboard_data,
                            client=(link["client_id"] or "").strip(),
                            advertiser_id=(link["advertiser_id"] or "").strip(),
                        )
                    dashboard = render_dashboard(dashboard_data)
                except Exception as exc:
                    tb = traceback.format_exc()
                    db.log_audit(user["id"], "dashboard.fail", str(exc)[:300], _client_ip(self))
                    _send_html(self, templates.render_error_page(str(exc), tb), 500)
                    return
        db.log_audit(user["id"], "dashboard.ok", "", _client_ip(self))
        _send_html(self, dashboard)

    def _post_internal_ml_link_attach(self):
        if not ML_LINK_ATTACH_SECRET:
            _send_json(self, {"ok": False, "message": "Segredo interno nao configurado"}, 500)
            return
        supplied = (
            self.headers.get("X-Internal-Secret")
            or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if not supplied or not secrets.compare_digest(ML_LINK_ATTACH_SECRET, supplied):
            _read_and_discard_body(self)
            _send_json(self, {"ok": False, "message": "Nao autorizado"}, 401)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > 50_000:
            _send_json(self, {"ok": False, "message": "Body invalido"}, 400)
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _send_json(self, {"ok": False, "message": "JSON invalido"}, 400)
            return
        bridge_state = str(payload.get("bridge_state") or "").strip()
        if not bridge_state:
            _send_json(self, {"ok": False, "message": "bridge_state obrigatorio"}, 400)
            return
        state_row = db.get_ml_link_state(bridge_state)
        if not state_row or state_row["expires_at"] < db.now():
            _send_json(self, {"ok": False, "message": "bridge_state expirado ou inexistente"}, 400)
            return
        account_id = db.upsert_user_ml_link(
            state_row["user_id"],
            client_id=str(payload.get("client_id") or "").strip(),
            ml_user_id=str(payload.get("ml_user_id") or "").strip(),
            nickname=str(payload.get("nickname") or "").strip(),
            official_store=str(payload.get("official_store") or "").strip(),
            advertiser_id=str(payload.get("advertiser_id") or "").strip(),
            seller_id=str(payload.get("seller_id") or "").strip(),
            site_id=str(payload.get("site_id") or "").strip(),
            status="active",
            slot_number=state_row["slot_number"],
        )
        db.mark_ml_link_state_attached(bridge_state)
        db.log_audit(state_row["user_id"], "ml_link.ok", str(payload.get("client_id") or ""), _client_ip(self))
        beta_synced = _sync_beta_user_if_enabled(state_row["user_id"])
        _send_json(self, {
            "ok": True,
            "account_id": account_id,
            "slot": state_row["slot_number"],
            "beta_synced": beta_synced,
        }, 200)

    def _post_webhook(self):
        if beta_config.BETA_MODE and beta_config.BETA_REJECT_BILLING_WEBHOOKS:
            _read_and_discard_body(self)
            _send_json(self, {
                "ok": False,
                "message": "Webhooks de cobranca ficam desativados no ambiente beta.",
                "beta": True,
            }, 404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > 2_000_000:
            _send_json(self, {"ok": False, "message": "Body invalido"}, 400)
            return
        raw = self.rfile.read(length)
        signature = self.headers.get("X-Signature") or self.headers.get("x-signature") or ""
        result = eduzz_webhook.process_event(raw, signature)
        _send_json(self, {"ok": result["ok"], "message": result["message"]}, result["status"])

    def _eduzz_oauth_callback(self, url):
        query = parse_qs(url.query or "")
        error = (query.get("error", [""])[0] or "").strip()
        if error:
            detail = (query.get("error_description", [""])[0] or error).strip()
            _redirect(self, f"/admin?info={quote('Eduzz recusou a conexao: ' + detail)}")
            return
        code = (query.get("code", [""])[0] or "").strip()
        state = (query.get("state", [""])[0] or "").strip()
        try:
            eduzz_api.exchange_code(code, state)
            _redirect(self, f"/admin?info={quote('API Eduzz conectada com sucesso')}")
        except eduzz_api.EduzzAPIError as exc:
            _send_html(self, templates.render_error_page(str(exc)), 400)

    def _post_eduzz_reconcile(self):
        expected = os.environ.get("EDUZZ_RECONCILE_SECRET", "")
        supplied = (
            self.headers.get("X-Internal-Secret")
            or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            _send_json(self, {"ok": False, "message": "Nao autorizado"}, 401)
            return
        try:
            result = eduzz_api.reconcile_subscriptions()
            _send_json(self, {"ok": True, "result": result})
        except eduzz_api.EduzzAPIError as exc:
            _send_json(self, {"ok": False, "message": str(exc)}, 503)

    def _internal_dash_ads_diagnostico(self, path: str, url):
        expected = os.environ.get("DASH_ADS_INTERNAL_SECRET") or os.environ.get("COMPETITIVE_WORKER_SECRET", "")
        supplied = (
            self.headers.get("X-COMPETITIVE-WORKER-SECRET")
            or self.headers.get("X-Internal-Secret")
            or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            _send_json(self, {"ok": False, "message": "Nao autorizado"}, 401)
            return

        route_map = {
            "/internal/dash-ads/ml-context": "/internal/dash-ads/ml-context",
            "/internal/dash-ads/ads-api-reconciliacao": "/internal/dash-ads/ads-api-reconciliacao",
            "/internal/dash-ads/vendas-items-reconciliacao": "/internal/dash-ads/vendas-items-reconciliacao",
            "/internal/dash-ads/item-change-probe": "/internal/dash-ads/item-change-probe",
            "/internal/dash-ads/online-cache-refresh": "/internal/dash-ads/online-cache-refresh",
            "/internal/dash-ads/online-cache-status": "/internal/dash-ads/online-cache-status",
            "/internal/dash-ads/online-cache-latest": "/internal/dash-ads/online-cache-latest",
        }
        upstream_path = route_map.get(path)
        if not upstream_path:
            _send_json(self, {"ok": False, "message": "Rota diagnostica nao permitida"}, 404)
            return

        allowed_params = {
            "client", "client_id", "site_id", "advertiser_id", "seller_id",
            "campaign_id", "item_id", "items", "date_from", "date_to",
            "include_mcp", "max_items",
        }
        query = parse_qs(url.query or "", keep_blank_values=True)
        clean_query = {
            key: values[-1]
            for key, values in query.items()
            if key in allowed_params and values
        }
        upstream_url = f"{AGENTE_ML_BASE_URL}{upstream_path}"
        if clean_query:
            upstream_url = f"{upstream_url}?{urlencode(clean_query)}"

        req = Request(
            upstream_url,
            headers={
                "Accept": "application/json",
                "X-COMPETITIVE-WORKER-SECRET": expected,
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=45) as response:
                raw = response.read(8_000_000)
                status = response.status
        except HTTPError as exc:
            raw = exc.read(8_000_000)
            status = exc.code
        except (URLError, TimeoutError) as exc:
            _send_json(self, {
                "ok": False,
                "source": "dash-ads",
                "upstream": "agente-ml",
                "message": "Falha ao consultar agente-ml.",
                "error": exc.__class__.__name__,
                "token_exposed": False,
            }, 502)
            return

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            payload = {
                "ok": False,
                "message": "agente-ml retornou resposta nao JSON.",
                "http_status": status,
            }
        if isinstance(payload, dict):
            payload.pop("access_token", None)
            payload.pop("refresh_token", None)
            payload.pop("client_secret", None)
            payload.setdefault("token_exposed", False)
            payload.setdefault("diagnostic_source", "agente-ml")
            payload.setdefault("dash_proxy", True)
        _send_json(self, payload if isinstance(payload, dict) else {"ok": False, "payload": payload}, status)

    def _eduzz_custom_delivery(self):
        # A entrega customizada da Eduzz faz um envio de teste para validar a URL.
        # Nao persistimos o payload aqui: o webhook assinado em /webhook/eduzz e
        # quem ativa ou suspende acesso com seguranca.
        if beta_config.BETA_MODE and beta_config.BETA_REJECT_BILLING_WEBHOOKS:
            _read_and_discard_body(self)
            _send_json(self, {
                "success": False,
                "message": "Entrega Eduzz fica desativada no ambiente beta.",
                "beta": True,
            }, 404)
            return
        _read_and_discard_body(self)
        _send_json(self, {
            "success": True,
            "message": "Entrega Eduzz recebida com sucesso.",
            "access_url": APP_PUBLIC_URL,
            "app": "Dashboard ADS Mercado Livre - Un Clic Marketplace",
        })

    def _beta_entry(self):
        user, _ = _current_user(self)
        if not beta_config.route_enabled():
            _send_html(self, templates.render_error_page("Ambiente beta nao esta habilitado neste servico."), 404)
            return
        if not user:
            if beta_config.BETA_SHARED_AUTH_URL and beta_config.BETA_PUBLIC_URL:
                target = f"{beta_config.BETA_SHARED_AUTH_URL}/beta/authorize?{urlencode({'return_to': beta_config.BETA_PUBLIC_URL + '/beta/callback'})}"
                _redirect(self, target)
            else:
                _redirect(self, "/login?return_to=/teste")
            return
        if not _beta_access_allowed(user):
            _send_html(self, templates.render_error_page("Este usuario nao esta autorizado para o ambiente beta."), 403)
            return
        link = db.get_active_ml_link_for_user(user["id"])
        linked_name = ""
        if link:
            linked_name = link["official_store"] or link["nickname"] or link["client_id"] or ""
        _send_html(self, templates.render_beta_entry(
            user["email"],
            linked_name,
            beta_config.shared_bridge_ready(),
            bool(link),
        ))

    def _beta_authorize(self, url):
        if not beta_config.bridge_enabled() or not beta_config.BETA_PUBLIC_URL:
            _send_html(self, templates.render_error_page("Ponte beta nao configurada neste servico."), 404)
            return
        qs = parse_qs(url.query or "")
        return_to = (qs.get("return_to", [""])[0] or "").strip().rstrip("/")
        expected = f"{beta_config.BETA_PUBLIC_URL}/beta/callback"
        if return_to != expected:
            _send_html(self, templates.render_error_page("Destino beta nao autorizado."), 400)
            return
        user, _ = _current_user(self)
        if not user:
            login_return = "/beta/authorize?" + urlencode({"return_to": expected})
            _redirect(self, "/login?" + urlencode({"return_to": login_return}))
            return
        if not _beta_access_allowed(user):
            _send_html(self, templates.render_error_page("Este usuario nao esta autorizado para o ambiente beta."), 403)
            return
        ml_accounts = db.list_active_ml_links_for_user(user["id"])
        assertion = beta_bridge.create_assertion(
            beta_config.BETA_SHARED_AUTH_SECRET,
            user,
            ml_accounts[0] if ml_accounts else None,
            expected,
            ml_accounts=ml_accounts,
        )
        _redirect(self, f"{expected}?{urlencode({'assertion': assertion})}")

    def _beta_callback(self, url):
        if not beta_config.route_enabled() or not beta_config.bridge_enabled():
            _send_html(self, templates.render_error_page("Ambiente beta nao esta habilitado."), 404)
            return
        qs = parse_qs(url.query or "")
        token = (qs.get("assertion", [""])[0] or "").strip()
        expected = f"{beta_config.BETA_PUBLIC_URL}/beta/callback"
        try:
            payload = beta_bridge.verify_assertion(token, beta_config.BETA_SHARED_AUTH_SECRET, expected)
            beta_enabled = payload["user"].get("beta_enabled")
            if beta_enabled is False or (
                beta_enabled is None and not beta_config.email_allowed(payload["user"]["email"])
            ):
                raise ValueError("usuario fora da lista beta")
            if not db.claim_beta_handoff(payload["nonce"], payload["exp"]):
                raise ValueError("assertion beta ja utilizada ou expirada")
            user_id = db.upsert_beta_identity(payload["user"])
            if "ml_accounts" in payload:
                db.sync_beta_ml_accounts(user_id, payload.get("ml_accounts") or [])
            else:
                ml_link = payload.get("ml") or {}
                if ml_link.get("client_id"):
                    db.upsert_user_ml_link(user_id, **ml_link)
            session_token = auth.new_session_token()
            db.create_session(user_id, session_token, _client_ip(self), self.headers.get("User-Agent", "")[:200])
            db.log_audit(user_id, "beta.bridge.login", "identity-only", _client_ip(self))
            _redirect(self, "/teste", set_cookie=auth.make_set_cookie(session_token))
        except (ValueError, KeyError, TypeError) as exc:
            _send_html(self, templates.render_error_page(f"Nao foi possivel abrir o beta: {exc}"), 400)

    def _post_admin_login(self):
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        password = form.get("password", "") or ""
        admin = db.get_admin(email)
        if not admin or not auth.verify_password(password, admin["password_hash"]):
            _send_html(self, templates.render_admin_login("Credenciais invalidas."), 401)
            return
        token = auth.create_admin_session(email)
        _redirect(self, "/admin", set_cookie=auth.make_admin_set_cookie(token))

    def _post_admin_reset_password(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        db.reset_user_password(user_id)
        db.log_audit(user_id, "admin.reset_password", admin["email"], _client_ip(self))
        _redirect(self, "/admin?info=Senha%20resetada%20com%20sucesso")

    def _post_admin_manual_access(self):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        name = (form.get("name", "") or "").strip()
        plan = (form.get("plan", "") or "").strip() or "cortesia"
        raw_days = (form.get("days", "") or "").strip()
        if not email:
            _send_html(self, templates.render_error_page("Informe um email valido."), 400)
            return
        try:
            days = int(raw_days or "7")
        except ValueError:
            _send_html(self, templates.render_error_page("Dias invalidos."), 400)
            return
        if days < 1 or days > 365:
            _send_html(self, templates.render_error_page("Dias devem ficar entre 1 e 365."), 400)
            return
        expires_at = int(time.time()) + (days * 86400)
        user_id = db.upsert_manual_user(
            email=email,
            name=name,
            plan=plan,
            status="active",
            expires_at=expires_at,
        )
        db.log_audit(user_id, f"admin.manual_access:{days}d", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user_id)
        _redirect(self, f"/admin?info=Acesso%20manual%20liberado%20por%20{days}%20dias")

    def _post_admin_bind_ml_link(self):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        client_id = (form.get("client_id", "") or "").strip()
        ml_user_id = (form.get("ml_user_id", "") or "").strip()
        nickname = (form.get("nickname", "") or "").strip()
        official_store = (form.get("official_store", "") or "").strip()
        advertiser_id = (form.get("advertiser_id", "") or "").strip()
        seller_id = (form.get("seller_id", "") or "").strip()
        site_id = ((form.get("site_id", "") or "MLB").strip() or "MLB").upper()
        try:
            slot_number = int((form.get("slot_number", "1") or "1").strip())
        except ValueError:
            _send_html(self, templates.render_error_page("Slot invalido."), 400)
            return
        if not email or not client_id:
            _send_html(self, templates.render_error_page("Informe o email e o client_id da conta ML."), 400)
            return
        user = db.get_user_by_email(email)
        if not user:
            _send_html(self, templates.render_error_page("Usuario nao encontrado para este email."), 404)
            return
        db.upsert_user_ml_link(
            user["id"],
            client_id=client_id,
            ml_user_id=ml_user_id,
            nickname=nickname,
            official_store=official_store,
            advertiser_id=advertiser_id,
            seller_id=seller_id,
            site_id=site_id,
            status="active",
            slot_number=slot_number,
            admin_granted=True,
            allow_replacement=True,
        )
        db.log_audit(user["id"], f"admin.bind_ml_link:{client_id}", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user["id"])
        _redirect(self, f"/admin?info=Conta%20ML%20vinculada%20com%20sucesso%20para%20{quote(email)}")

    def _post_admin_set_ml_slot_limit(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        form = _parse_form(self)
        try:
            slot_limit = int((form.get("slot_limit", "") or "").strip())
            db.set_user_ml_slot_limit(user_id, slot_limit)
        except ValueError as exc:
            _send_html(self, templates.render_error_page(str(exc)), 400)
            return
        db.log_audit(user_id, f"admin.ml_slot_limit:{slot_limit}", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user_id)
        _redirect(self, f"/admin?info=Limite%20de%20contas%20alterado%20para%20{slot_limit}")

    def _post_admin_grant_access(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        form = _parse_form(self)
        try:
            days = int((form.get("days", "") or "").strip())
        except ValueError:
            _send_html(self, templates.render_error_page("Dias invalidos."), 400)
            return
        if days < 1 or days > 365:
            _send_html(self, templates.render_error_page("Dias devem ficar entre 1 e 365."), 400)
            return
        expires_at = int(time.time()) + (days * 86400)
        db.set_user_access_window(user_id, status="active", expires_at=expires_at)
        db.log_audit(user_id, f"admin.grant_access:{days}d", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user_id)
        _redirect(self, f"/admin?info=Acesso%20renovado%20por%20{days}%20dias")

    def _post_admin_set_status(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        form = _parse_form(self)
        new_status = (form.get("status", "") or "").strip()
        if new_status not in ("active", "suspended", "expired", "refunded", "pending"):
            _send_html(self, templates.render_error_page("Status invalido."), 400)
            return
        if new_status == "active":
            # Ativacao manual via admin precisa realmente destravar o acesso.
            # Se o usuario estava vencido, manter expires_at antigo continua bloqueando no login.
            db.set_user_access_window(user_id, status="active", expires_at=None)
        else:
            db.set_user_status(user_id, new_status)
        db.log_audit(user_id, f"admin.set_status:{new_status}", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user_id)
        _redirect(self, f"/admin?info=Status%20alterado%20para%20{new_status}")

    def _post_admin_set_beta_access(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        form = _parse_form(self)
        enabled_raw = (form.get("enabled", "") or "").strip()
        if enabled_raw not in ("0", "1"):
            _send_html(self, templates.render_error_page("Acesso beta invalido."), 400)
            return
        enabled = enabled_raw == "1"
        db.set_user_beta_access(user_id, enabled)
        user = db.get_user_by_id(user_id)
        if not user:
            _send_html(self, templates.render_error_page("Usuario nao encontrado."), 404)
            return
        if beta_config.BETA_MODE and not enabled:
            db.delete_user_sessions(user_id)
        synced = _sync_beta_access(user)
        action = "liberado" if enabled else "bloqueado"
        db.log_audit(user_id, f"admin.beta_access:{action}", admin["email"], _client_ip(self))
        if synced:
            info = f"Acesso beta {action} com sucesso"
        else:
            info = f"Acesso beta {action}; sincronizacao com o beta pendente"
        _redirect(self, "/admin?" + urlencode({"info": info}))

    def _post_admin_set_sales_access(self, path: str):
        admin, _ = _current_admin(self)
        if not admin:
            _redirect(self, "/admin/login")
            return
        try:
            user_id = int(path.split("/")[3])
        except (ValueError, IndexError):
            _send_html(self, templates.render_error_page("ID invalido."), 400)
            return
        form = _parse_form(self)
        enabled_raw = (form.get("enabled", "") or "").strip()
        if enabled_raw not in ("0", "1"):
            _send_html(self, templates.render_error_page("Acesso da Inteligencia de Vendas invalido."), 400)
            return
        enabled = enabled_raw == "1"
        db.set_user_sales_access(user_id, enabled)
        action = "liberada" if enabled else "bloqueada"
        db.log_audit(user_id, f"admin.sales_access:{action}", admin["email"], _client_ip(self))
        _sync_beta_user_if_enabled(user_id)
        _redirect(self, "/admin?" + urlencode({"info": f"Inteligencia de Vendas {action} com sucesso"}))

    def _post_internal_beta_access_sync(self):
        if not beta_config.BETA_MODE or not beta_config.bridge_enabled():
            _send_json(self, {"ok": False, "message": "Sincronizacao beta indisponivel"}, 404)
            return
        form = _parse_form(self)
        token = (form.get("assertion", "") or "").strip()
        audience = f"{beta_config.BETA_PUBLIC_URL}/internal/beta/access-sync"
        try:
            payload = beta_bridge.verify_assertion(
                token,
                beta_config.BETA_SHARED_AUTH_SECRET,
                audience,
            )
            beta_enabled = payload["user"].get("beta_enabled")
            if beta_enabled is None:
                raise ValueError("permissao beta ausente")
            if not db.claim_beta_handoff(payload["nonce"], payload["exp"]):
                raise ValueError("sincronizacao beta repetida ou expirada")
            user_id = db.upsert_beta_identity(payload["user"])
            account_count = 0
            if "ml_accounts" in payload:
                account_count = db.sync_beta_ml_accounts(user_id, payload.get("ml_accounts") or [])
            else:
                ml_link = payload.get("ml") or {}
                if ml_link.get("client_id"):
                    db.upsert_user_ml_link(user_id, **ml_link)
                    account_count = 1
            if not beta_enabled:
                db.delete_user_sessions(user_id)
            action = "liberado" if beta_enabled else "bloqueado"
            db.log_audit(user_id, f"beta.access_sync:{action}", "signed-bridge", _client_ip(self))
            _send_json(self, {
                "ok": True,
                "beta_enabled": bool(beta_enabled),
                "account_count": account_count,
            })
        except (ValueError, KeyError, TypeError) as exc:
            _send_json(self, {"ok": False, "message": str(exc)}, 400)

# ------------------ Bootstrap ------------------

def bootstrap():
    """Inicializa banco e admin a partir de variaveis de ambiente."""
    db.init_db()
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and admin_password:
        try:
            pwd_hash = auth.hash_password(admin_password)
            db.ensure_admin(admin_email, pwd_hash)
            print(f"[bootstrap] admin pronto: {admin_email}")
        except ValueError as exc:
            print(f"[bootstrap] admin nao configurado: {exc}")
    else:
        print("[bootstrap] ADMIN_EMAIL/ADMIN_PASSWORD nao definidos - painel admin ficara inacessivel ate definir.")
    if not os.environ.get("EDUZZ_WEBHOOK_SECRET"):
        print("[bootstrap] AVISO: EDUZZ_WEBHOOK_SECRET nao definido - webhook rejeitara tudo.")


def main():
    bootstrap()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[app] ouvindo em http://{HOST}:{PORT}  (versao: {APP_VERSION})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] encerrando...")
        server.shutdown()


if __name__ == "__main__":
    main()
