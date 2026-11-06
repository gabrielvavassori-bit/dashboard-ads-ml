"""Read-only projections for a user's linked Mercado Livre accounts."""

from collections import defaultdict
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode


def project_account(account, dashboard):
    """Keep only the fields needed by the virtual view; never retain raw cache."""
    meta = dashboard.get("meta") or {}
    online = meta.get("onlineMode") or {}
    period = meta.get("period") or {}
    label = account["official_store"] or account["nickname"] or account["client_id"]
    return {
        "id": int(account["id"]), "label": str(label), "client_id": str(account["client_id"]),
        "period": (period.get("dateFrom"), period.get("dateTo")),
        "complete": bool(online.get("complete")) and bool(online.get("periodMatch"))
                    and all(not row.get("partial", True) for row in dashboard.get("accountDailySeries") or []),
        "kpis": {key: dashboard.get("kpis", {}).get(key) for key in
                 ("revenue", "investment", "adsRevenue", "units", "products", "tacosBaseRevenue")},
        "daily": [{key: row.get(key) for key in
                   ("date", "revenue", "investment", "adsRevenue", "units", "partial")}
                  for row in dashboard.get("accountDailySeries") or []],
        "items": [{key: row.get(key) for key in
                   ("code", "sku", "title", "familyId", "familyName", "totalRevenue", "units", "orders", "investment", "adsRevenue")}
                  for row in dashboard.get("items") or []],
    }


def combine(accounts, start, end):
    """Aggregate only exact-window accounts; incomplete sources remain explicit."""
    expected = (start, end)
    accepted = [a for a in accounts if a["period"] == expected]
    complete = len(accepted) == len(accounts) and all(a["complete"] for a in accepted)
    sums = {key: sum(float(a["kpis"].get(key) or 0) for a in accepted)
            for key in ("revenue", "investment", "adsRevenue", "units", "tacosBaseRevenue")}
    sums["tacos"] = sums["investment"] / sums["tacosBaseRevenue"] if sums["tacosBaseRevenue"] else None
    daily = defaultdict(lambda: {"revenue": 0.0, "investment": 0.0, "adsRevenue": 0.0, "units": 0.0, "sources": 0})
    for account in accepted:
        for row in account["daily"]:
            day = str(row.get("date") or "")
            if not start <= day <= end or row.get("partial"):
                continue
            target = daily[day]
            for key in ("revenue", "investment", "adsRevenue", "units"):
                target[key] += float(row.get(key) or 0)
            target["sources"] += 1
    cursor, last = date.fromisoformat(start), date.fromisoformat(end)
    chart = []
    while cursor <= last:
        day = cursor.isoformat()
        row = daily.get(day)
        chart.append({"date": day, **row} if row and row["sources"] == len(accepted) else {"date": day, "missing": True})
        cursor += timedelta(days=1)
    complete = complete and all(not row.get("missing") for row in chart)
    items = []
    for account in accepted:
        for item in account["items"]:
            items.append({**item, "account": account["label"], "account_id": account["id"]})
    return {"complete": complete, "accepted": len(accepted), "selected": len(accounts),
            "sums": sums, "chart": chart, "items": items}


def _money(value):
    return "R$ " + f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _group_items(items, view):
    if view == "anuncio":
        return sorted(items, key=lambda row: -float(row.get("totalRevenue") or 0))
    groups = {}
    for item in items:
        if view in ("familia", "hibrida") and (view == "familia" or item.get("familyId")):
            identity = item.get("familyId") or item.get("code") or "sem-familia"
            title = item.get("familyName") or item.get("title") or identity
        elif view == "hibrida":
            identity = item.get("code") or item.get("sku") or "sem-anuncio"
            title = item.get("title") or identity
        else:
            identity = item.get("sku") or item.get("code") or "sem-sku"
            title = identity
        key = (item["account_id"], identity)
        if key not in groups:
            groups[key] = {"account": item["account"], "code": identity,
                           "sku": identity if view == "sku" else "", "title": title,
                           "totalRevenue": 0.0, "units": 0.0, "orders": 0.0,
                           "investment": 0.0, "adsRevenue": 0.0}
        for field in ("totalRevenue", "units", "orders", "investment", "adsRevenue"):
            groups[key][field] += float(item.get(field) or 0)
    return sorted(groups.values(), key=lambda row: -row["totalRevenue"])


def render(accounts, selected_ids, period, projections, failures, view="hibrida", page=1):
    """Independent page: no writes, promotions, or cross-account API calls."""
    from templates import _layout

    view = view if view in ("hibrida", "familia", "anuncio", "sku") else "hibrida"
    selected = [a for a in accounts if int(a["id"]) in selected_ids]
    result = combine(projections, period["dateFrom"], period["dateTo"]) if projections else None
    overall_complete = bool(result and not failures and len(projections) == len(selected) and result["complete"])
    options = "".join(
        '<label class="account"><input type="checkbox" name="account_id" value="{}" {}> {} <small>({})</small></label>'.format(
            int(a["id"]), "checked" if int(a["id"]) in selected_ids else "",
            escape(str(a["official_store"] or a["nickname"] or a["client_id"])),
            escape(str(a["client_id"]))) for a in accounts)
    warning = ""
    if not overall_complete:
        names = ", ".join(escape(name) for name in failures)
        warning = '<div class="alert err">Visão incompleta: {}. Os totais abaixo incluem somente contas com leitura disponível da janela exata; não são o total de todas as contas selecionadas.</div>'.format(
            "falha em " + names if names else "há dias ou contas sem certificação")
    cards = chart = table = ""
    if result:
        sums = result["sums"]
        kpi_rows = [("Faturamento bruto", _money(sums["revenue"])),
                    ("Investimento Ads", _money(sums["investment"])),
                    ("Receita atribuída Ads", _money(sums["adsRevenue"])),
                    ("Unidades", f'{sums["units"]:,.0f}'.replace(",", ".")),
                    ("TACOS geral", f'{sums["tacos"]*100:.2f}%'.replace(".", ",") if sums["tacos"] is not None else "N/D")]
        cards = '<div class="cards">' + "".join('<div class="card"><small>{}</small><strong>{}</strong></div>'.format(escape(label), escape(value)) for label, value in kpi_rows) + '</div>'
        if overall_complete:
            values = [float(row["revenue"]) for row in result["chart"]]
            ceiling = max(values) or 1
            bars = "".join('<div class="bar" style="height:{:.1f}%" title="{}: {}"></div>'.format(
                value / ceiling * 100, escape(row["date"]), escape(_money(value)))
                for row, value in zip(result["chart"], values))
            chart = '<h2>Faturamento diário consolidado</h2><div class="chart">{}</div><small>{} a {}</small>'.format(
                bars, escape(period["dateFrom"]), escape(period["dateTo"]))
        else:
            chart = '<p>Gráfico N/D: nem todas as contas e datas da seleção estão completas.</p>'
        rows = _group_items(result["items"], view)
        table = '<nav>' + " ".join('<a href="?{}">{}</a>'.format(
            escape(urlencode([("account_id", str(i)) for i in sorted(selected_ids)] + [("view", mode)]), quote=True),
            escape(title)) for mode, title in (("hibrida", "Híbrida"), ("familia", "Família"), ("anuncio", "Anúncio"), ("sku", "SKU"))) + '</nav>'
        table += '<div class="scroll"><table><thead><tr><th>Conta</th><th>Produto / agrupamento</th><th>MLB / SKU</th><th>Receita</th><th>Unidades</th><th>Investimento</th><th>TACOS</th></tr></thead><tbody>'
        page = max(1, min(int(page), max(1, (len(rows) + 99) // 100)))
        for item in rows[(page - 1) * 100:page * 100]:
            revenue = float(item.get("totalRevenue") or 0)
            investment = float(item.get("investment") or 0)
            tacos = f'{investment/revenue*100:.2f}%'.replace(".", ",") if revenue else "N/D"
            table += '<tr><td>{}</td><td>{}</td><td>{}<br>{}</td><td>{}</td><td>{:,.0f}</td><td>{}</td><td>{}</td></tr>'.format(
                escape(str(item.get("account") or "")), escape(str(item.get("title") or "")),
                escape(str(item.get("code") or "")), escape(str(item.get("sku") or "")),
                escape(_money(revenue)), float(item.get("units") or 0), escape(_money(investment)), tacos)
        table += '</tbody></table></div><small>Página {} de {} · {} linhas, ordenadas por receita. SKUs iguais de contas diferentes permanecem separados.</small>'.format(
            page, max(1, (len(rows) + 99) // 100), len(rows))
        def page_link(number, title):
            query = [("account_id", str(i)) for i in sorted(selected_ids)]
            query.extend((("view", view), ("page", str(number))))
            return '<a href="?{}">{}</a>'.format(escape(urlencode(query), quote=True), title)
        table += '<nav>{} {}</nav>'.format(page_link(page - 1, "Anterior") if page > 1 else "",
                                             page_link(page + 1, "Próxima") if page * 100 < len(rows) else "")
    css = '''<style>main{max-width:1400px;margin:20px auto}.accounts{display:flex;flex-wrap:wrap;gap:10px}.account{margin:0;padding:8px;border:1px solid #d9e1ec;border-radius:8px}.account small{font-weight:normal}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{border:1px solid #d9e1ec;border-radius:9px;padding:14px}.card strong{display:block;font-size:22px}.chart{height:240px;display:flex;align-items:flex-end;gap:3px;border-bottom:1px solid #d9e1ec}.bar{flex:1;min-width:3px;background:#8b6be0}.scroll{overflow-x:auto}nav{margin:18px 0}nav a{margin-right:18px}form button{width:auto;margin-top:12px}input[type=checkbox]{width:auto}</style>'''
    body = '<h1>Visão consolidada das contas</h1><p>Selecione as contas vinculadas a este cliente. Esta visão é somente leitura e não ocupa um slot ML.</p>'
    body += '<p><a href="/contas">Contas</a> · <a href="/online?confirmed=1">Dashboard individual</a></p>'
    body += '<form method="get" action="/online/consolidado"><input type="hidden" name="selection" value="1"><div class="accounts">{}</div><button type="submit">Atualizar seleção</button></form>'.format(options)
    body += '<p>Período: {} a {} · {} de {} conta(s) com dados da janela exata.</p>'.format(
        escape(period["dateFrom"]), escape(period["dateTo"]), result["accepted"] if result else 0, len(selected))
    return _layout("Visão consolidada", body + warning + cards + chart + table, css)
