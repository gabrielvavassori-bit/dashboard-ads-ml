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

Endpoints admin:
  GET  /admin           -> lista clientes
  GET  /admin/login     -> login admin
  POST /admin/login     -> processa
  GET  /admin/logout    -> sair
  POST /admin/users/<id>/reset_password
  POST /admin/users/<id>/set_status

Variaveis de ambiente:
  PORT                    Porta (padrao 4182)
  DATA_DIR                Pasta do banco SQLite (padrao ./data, em prod /var/data)
  APP_PUBLIC_URL          URL publica do app (ex: https://dashboard.unclic.com.br)
  EDUZZ_WEBHOOK_SECRET    Chave configurada na Eduzz para assinar webhooks
  EDUZZ_PRODUCT_IDS       IDs dos produtos validos, separados por virgula (opcional)
  DEFAULT_ACCESS_DAYS     Dias de acesso quando o payload nao traz nextChargeDate
  ADMIN_EMAIL             Email do admin
  ADMIN_PASSWORD          Senha do admin (so usada no boot para criar/atualizar)
  MAX_UPLOAD_MB           Limite por arquivo (padrao 20)
"""
import html as _html
import json
import os
import pathlib
import tempfile
import traceback
import threading
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import auth
import db
import templates
import webhook as eduzz_webhook
from gerar_dashboard_ads_ml import build_data, render_dashboard

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "4182"))
APP_VERSION = "Meli beta v6 - online"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# Limita 2 arquivos + overhead de multipart
MAX_BODY_BYTES = MAX_UPLOAD_BYTES * 2 + 1 * 1024 * 1024

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


def _current_admin(handler):
    cookies = _get_cookies(handler)
    token = cookies.get(auth.ADMIN_COOKIE)
    return auth.get_admin_session(token), token


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
            if path == "/login":
                user, _ = _current_user(self)
                if user:
                    _redirect(self, "/")
                    return
                _send_html(self, templates.render_login())
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
            if path == "/admin" or path == "/admin/":
                admin, _ = _current_admin(self)
                if not admin:
                    _redirect(self, "/admin/login")
                    return
                qs = parse_qs(url.query or "")
                q = (qs.get("q", [""])[0] or "").strip()
                users = db.list_users(q)
                info = (qs.get("info", [""])[0] or "")
                _send_html(self, templates.render_admin_users(users, q, info))
                return
            if path == "/":
                user, _ = _current_user(self)
                if not user:
                    _redirect(self, "/login")
                    return
                _send_html(self, templates.render_app_shell(user["name"] or user["email"], APP_VERSION))
                return

            _send_html(self, templates.render_error_page("Pagina nao encontrada."), 404)
        except Exception as exc:
            tb = traceback.format_exc()
            _send_html(self, templates.render_error_page(str(exc), tb), 500)

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
            if path == "/admin/login":
                self._post_admin_login()
                return
            if path.startswith("/admin/users/") and path.endswith("/reset_password"):
                self._post_admin_reset_password(path)
                return
            if path.startswith("/admin/users/") and path.endswith("/set_status"):
                self._post_admin_set_status(path)
                return

            _send_html(self, templates.render_error_page("Rota nao encontrada."), 404)
        except Exception as exc:
            tb = traceback.format_exc()
            _send_html(self, templates.render_error_page(str(exc), tb), 500)

    # ----------- Handlers especificos -----------

    def _post_login(self):
        form = _parse_form(self)
        email = (form.get("email", "") or "").strip().lower()
        password = form.get("password", "") or ""
        if not email or not password:
            _send_html(self, templates.render_login("Informe email e senha.", email=email), 400)
            return
        user = db.get_user_by_email(email)
        if not user or not user["password_hash"] or not auth.verify_password(password, user["password_hash"]):
            db.log_audit(user["id"] if user else None, "login.fail", email, _client_ip(self))
            _send_html(self, templates.render_login("Email ou senha invalidos.", email=email), 401)
            return
        if not auth.user_is_active(user):
            db.log_audit(user["id"], "login.inactive", user["status"], _client_ip(self))
            _send_html(self, templates.render_login(
                "Sua assinatura nao esta ativa. Verifique seu pagamento na Eduzz ou fale com o suporte.", email=email
            ), 403)
            return
        token = auth.new_session_token()
        db.create_session(user["id"], token, _client_ip(self), self.headers.get("User-Agent", "")[:200])
        db.log_audit(user["id"], "login.ok", "", _client_ip(self))
        _redirect(self, "/", set_cookie=auth.make_set_cookie(token))

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
            files, _ = _parse_multipart(self)
        except ValueError as exc:
            _send_html(self, templates.render_app_shell(user["name"] or user["email"], APP_VERSION, str(exc)), 400)
            return
        if "sales" not in files or "ads" not in files:
            _send_html(self, templates.render_app_shell(
                user["name"] or user["email"], APP_VERSION,
                "Envie os dois arquivos: planilha de vendas e relatorio de publicidade."
            ), 400)
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
                    dashboard = render_dashboard(build_data(sales_path, ads_path))
                except Exception as exc:
                    tb = traceback.format_exc()
                    db.log_audit(user["id"], "dashboard.fail", str(exc)[:300], _client_ip(self))
                    _send_html(self, templates.render_error_page(str(exc), tb), 500)
                    return
        db.log_audit(user["id"], "dashboard.ok", "", _client_ip(self))
        _send_html(self, dashboard)

    def _post_webhook(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > 2_000_000:
            _send_json(self, {"ok": False, "message": "Body invalido"}, 400)
            return
        raw = self.rfile.read(length)
        signature = self.headers.get("X-Signature") or self.headers.get("x-signature") or ""
        result = eduzz_webhook.process_event(raw, signature)
        _send_json(self, {"ok": result["ok"], "message": result["message"]}, result["status"])

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
        db.set_user_status(user_id, new_status)
        db.log_audit(user_id, f"admin.set_status:{new_status}", admin["email"], _client_ip(self))
        _redirect(self, f"/admin?info=Status%20alterado%20para%20{new_status}")


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
