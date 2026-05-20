"""
Templates HTML (apenas strings). Mantemos o mesmo visual usado no app original.
"""
import html as _html

BRAND = "Un Clic Marketplace"
APP_NAME = "Dashboard ADS Mercado Livre"


def _layout(title: str, body: str, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html.escape(title)} - {BRAND}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#f5f7fb; color:#101828; font:15px/1.45 Arial,sans-serif; }}
    main {{ max-width:560px; margin:60px auto; background:#fff; border:1px solid #d9e1ec;
            border-radius:14px; padding:32px; box-shadow:0 8px 24px rgba(16,24,40,.07); }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    .brand {{ color:#667085; font-size:12px; font-weight:800; text-transform:uppercase;
              letter-spacing:.04em; margin-bottom:18px; }}
    p  {{ color:#475467; margin:0 0 16px; }}
    label {{ display:block; font-weight:700; margin:16px 0 6px; font-size:14px; }}
    input[type=email], input[type=password], input[type=text] {{
      width:100%; padding:12px 14px; border:1px solid #cfd6e4; border-radius:10px;
      font-size:15px; background:#fff;
    }}
    input:focus {{ outline:2px solid #1e5fbf; border-color:#1e5fbf; }}
    button {{ margin-top:22px; padding:13px 18px; border:0; border-radius:10px;
              background:#102033; color:#fff; font-weight:800; cursor:pointer; width:100%;
              font-size:15px; }}
    button:hover {{ background:#1b3354; }}
    .alert {{ padding:12px 14px; border-radius:10px; margin-bottom:16px; font-size:14px; }}
    .alert.err {{ background:#fde8e8; color:#9b1c1c; border:1px solid #f3c4c4; }}
    .alert.ok  {{ background:#e8f5e9; color:#1b5e20; border:1px solid #c8e6c9; }}
    .hint {{ font-size:13px; color:#667085; margin-top:6px; }}
    a {{ color:#1e5fbf; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .footer {{ text-align:center; color:#667085; font-size:12px; margin-top:20px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid #eaecf0; text-align:left; }}
    th {{ background:#f5f7fb; font-weight:700; }}
    .pill {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:700; }}
    .pill.active {{ background:#e6f4ea; color:#1b5e20; }}
    .pill.suspended {{ background:#fff4e5; color:#974b00; }}
    .pill.expired, .pill.refunded {{ background:#fde8e8; color:#9b1c1c; }}
    .pill.pending {{ background:#eef2ff; color:#1e3a8a; }}
    .row-actions form {{ display:inline-block; margin-right:6px; }}
    .row-actions button {{ width:auto; padding:6px 10px; font-size:12px; margin:0;
                            background:#e8eef7; color:#102033; }}
    .row-actions button.danger {{ background:#fde8e8; color:#9b1c1c; }}
  </style>
  {extra_head}
</head>
<body>
<main>
  <div class="brand">{BRAND} · {APP_NAME}</div>
  {body}
  <div class="footer">© {BRAND}</div>
</main>
</body>
</html>"""


def render_login(error: str = "", info: str = "", email: str = "") -> str:
    err_html = f'<div class="alert err">{_html.escape(error)}</div>' if error else ""
    info_html = f'<div class="alert ok">{_html.escape(info)}</div>' if info else ""
    body = f"""
    <h1>Entrar</h1>
    <p>Acesse com o email da sua compra na Eduzz e a sua senha.</p>
    {err_html}{info_html}
    <form method="post" action="/login">
      <label>Email</label>
      <input type="email" name="email" required value="{_html.escape(email)}" autocomplete="email">
      <label>Senha</label>
      <input type="password" name="password" required autocomplete="current-password">
      <button type="submit">Entrar</button>
    </form>
    <p class="hint" style="margin-top:18px">
      Primeira vez? <a href="/cadastrar">Crie sua senha</a><br>
      Esqueceu a senha? Entre em contato com o suporte.
    </p>
    """
    return _layout("Entrar", body)


def render_register(error: str = "", email: str = "") -> str:
    err_html = f'<div class="alert err">{_html.escape(error)}</div>' if error else ""
    body = f"""
    <h1>Criar senha de acesso</h1>
    <p>Use o mesmo email que voce informou na compra da Eduzz. So conseguimos criar uma senha para emails com assinatura ativa.</p>
    {err_html}
    <form method="post" action="/cadastrar">
      <label>Email da compra</label>
      <input type="email" name="email" required value="{_html.escape(email)}" autocomplete="email">
      <label>Nova senha (minimo 6 caracteres)</label>
      <input type="password" name="password" required minlength="6" autocomplete="new-password">
      <label>Confirme a senha</label>
      <input type="password" name="password2" required minlength="6" autocomplete="new-password">
      <button type="submit">Criar senha</button>
    </form>
    <p class="hint" style="margin-top:18px"><a href="/login">Voltar para entrar</a></p>
    """
    return _layout("Cadastrar", body)


def render_app_shell(user_name: str, version: str, error: str = "") -> str:
    """Tela principal apos login - formulario de upload dos arquivos."""
    err_html = f'<div class="alert err">{_html.escape(error)}</div>' if error else ""
    extra_css = """
    main { max-width: 840px; }
    .topbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }
    .topbar small { color:#667085; }
    .upload { border:1px dashed #98a2b3; border-radius:10px; padding:14px; background:#f8fafc; }
    .box { background:#f0f4f8; border:1px solid #d9e1ec; border-radius:10px; padding:14px; margin-top:18px; font-size:14px; color:#344054;}
    """
    extra_head = f"<style>{extra_css}</style>"
    body = f"""
    <div class="topbar">
      <div>
        <h1 style="margin:0">Gerador de Dashboard ADS Mercado Livre</h1>
        <small>{_html.escape(version)}</small>
      </div>
      <div style="text-align:right">
        <div style="font-size:13px;color:#475467">Ola, {_html.escape(user_name or 'cliente')}</div>
        <a href="/logout" style="font-size:13px">sair</a>
      </div>
    </div>

    <p>Envie a planilha de vendas do Mercado Livre e o relatorio de publicidade. O dashboard sera gerado na hora, sem alterar seus arquivos.</p>
    {err_html}
    <form method="post" enctype="multipart/form-data" action="/gerar">
      <label>1. Planilha de vendas do Mercado Livre</label>
      <input type="file" name="sales" accept=".xlsx" required class="upload">
      <div class="hint">Use o arquivo baixado direto do Mercado Livre. Se ele ja tiver abas consolidadas, o app aproveita automaticamente.</div>

      <label>2. Relatorio de publicidade</label>
      <input type="file" name="ads" accept=".xlsx" required class="upload">
      <div class="hint">Exemplo: arquivo com aba <b>Relatorio Anuncios patrocinados</b>.</div>

      <button type="submit">Gerar dashboard</button>
    </form>
    <div class="box">
      Cada arquivo pode ter ate 20 MB. Esta versao usa duas paginas internas: Operacional e Curva ABC.
    </div>
    """
    return _layout("Painel", body, extra_head)


def render_error_page(message: str, traceback_text: str = "") -> str:
    tb = f'<pre style="white-space:pre-wrap;background:#f5f7fb;border:1px solid #d9e1ec;padding:12px;border-radius:8px;font-size:12px;color:#475467">{_html.escape(traceback_text)}</pre>' if traceback_text else ""
    body = f"""
    <h1>Nao consegui gerar o dashboard</h1>
    <p>Confira se voce enviou a planilha de vendas do Mercado Livre e o relatorio de publicidade correto.</p>
    <div class="alert err">{_html.escape(message)}</div>
    {tb}
    <p><a href="/">Voltar para o painel</a></p>
    """
    return _layout("Erro", body)


def render_admin_login(error: str = "") -> str:
    err_html = f'<div class="alert err">{_html.escape(error)}</div>' if error else ""
    body = f"""
    <h1>Painel administrativo</h1>
    {err_html}
    <form method="post" action="/admin/login">
      <label>Email</label>
      <input type="email" name="email" required autocomplete="email">
      <label>Senha</label>
      <input type="password" name="password" required autocomplete="current-password">
      <button type="submit">Entrar</button>
    </form>
    """
    return _layout("Admin - Login", body)


def render_admin_users(users, query: str = "", info: str = "") -> str:
    import time
    info_html = f'<div class="alert ok">{_html.escape(info)}</div>' if info else ""

    def fmt_ts(ts):
        if not ts:
            return "-"
        try:
            return time.strftime("%d/%m/%Y %H:%M", time.localtime(int(ts)))
        except Exception:
            return "-"

    rows = []
    for u in users:
        status = u["status"] or "pending"
        plan = (u["plan"] or "")[:30]
        has_pwd = "sim" if u["password_hash"] else "nao"
        rows.append(f"""
        <tr>
          <td>{_html.escape(u['email'] or '')}<div style="font-size:12px;color:#667085">{_html.escape(u['name'] or '')}</div></td>
          <td><span class="pill {status}">{status}</span></td>
          <td>{_html.escape(plan)}</td>
          <td>{fmt_ts(u['expires_at'])}</td>
          <td>{has_pwd}</td>
          <td>{fmt_ts(u['created_at'])}</td>
          <td class="row-actions">
            <form method="post" action="/admin/users/{u['id']}/reset_password" onsubmit="return confirm('Limpar senha e derrubar sessoes ativas?')">
              <button type="submit">Resetar senha</button>
            </form>
            <form method="post" action="/admin/users/{u['id']}/set_status">
              <input type="hidden" name="status" value="active">
              <button type="submit">Ativar</button>
            </form>
            <form method="post" action="/admin/users/{u['id']}/set_status">
              <input type="hidden" name="status" value="suspended">
              <button type="submit" class="danger">Suspender</button>
            </form>
          </td>
        </tr>""")

    extra_css = "main { max-width: 1100px; }"
    body = f"""
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h1 style="margin:0">Clientes</h1>
      <div><a href="/admin/logout">sair</a></div>
    </div>
    {info_html}
    <form method="get" action="/admin" style="margin:18px 0">
      <input type="text" name="q" value="{_html.escape(query)}" placeholder="Buscar por email ou nome">
      <button type="submit" style="width:auto;display:inline-block;margin-left:8px">Buscar</button>
    </form>
    <table>
      <thead>
        <tr><th>Email/Nome</th><th>Status</th><th>Plano</th><th>Expira em</th><th>Senha?</th><th>Criado</th><th>Acoes</th></tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="7" style="text-align:center;color:#667085;padding:24px">Nenhum cliente encontrado.</td></tr>'}
      </tbody>
    </table>
    """
    return _layout("Admin - Clientes", body, f"<style>{extra_css}</style>")
