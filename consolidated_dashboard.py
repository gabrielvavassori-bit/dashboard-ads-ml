"""Read-only projections for a user's linked Mercado Livre accounts."""

from collections import defaultdict
from datetime import date, timedelta
from html import escape
import json
from urllib.parse import urlencode


SUM_FIELDS = ("revenue", "investment", "adsRevenue", "units", "tacosBaseRevenue")
DAILY_FIELDS = ("revenue", "investment", "adsRevenue", "units", "orders", "visits")
ITEM_FIELDS = ("code", "sku", "skuIsReference", "title", "familyId", "familyName", "userProductId",
               "userProductName", "campaign", "campaignId", "campaignName",
               "totalRevenue", "units", "orders", "investment", "adsRevenue",
               "visits", "visitsCoverageComplete", "impressions", "clicks", "thumbnailUrl")


def project_account(account, dashboard):
    """Keep only the fields needed by the virtual view; never retain raw cache."""
    meta = dashboard.get("meta") or {}
    online = meta.get("onlineMode") or {}
    period = meta.get("period") or {}
    label = account["official_store"] or account["nickname"] or account["client_id"]
    official = dashboard.get("accountMetrics") or {}
    visits_complete = (official.get("visits", {}).get("complete") is True) or (bool(dashboard.get("items")) and all(
        item.get("visitsCoverageComplete") is True for item in dashboard.get("items") or [])
    )
    return {
        "id": int(account["id"]), "label": str(label), "client_id": str(account["client_id"]),
        "period": (period.get("dateFrom"), period.get("dateTo")),
        "complete": bool(online.get("complete")) and bool(online.get("periodMatch"))
                    and all(not row.get("partial", True) for row in dashboard.get("accountDailySeries") or []),
        "kpis": {key: dashboard.get("kpis", {}).get(key) for key in
                 (*SUM_FIELDS, "products", "organicRevenue", "returnsAmount", "returnsAvailable",
                  "returnsOrdersCount", "returnsOrdersAvailable", "adsNoSales",
                  "investmentNoAdsSales")},
        "visits_complete": visits_complete,
        "cancelled_orders": (official.get("cancelledOrders", {}).get("total")
                             if official.get("cancelledOrders", {}).get("complete") is True else None),
        "daily": [{**{key: row.get(key) for key in ("date", *DAILY_FIELDS, "partial")},
                   "visits": row.get("visits") if visits_complete else None}
                  for row in dashboard.get("accountDailySeries") or []],
        "items": [{key: row.get(key) for key in
                   ITEM_FIELDS}
                  for row in dashboard.get("items") or []],
    }


def combine(accounts, start, end):
    """Aggregate only exact-window accounts; incomplete sources remain explicit."""
    expected = (start, end)
    accepted = [a for a in accounts if a["period"] == expected]
    complete = len(accepted) == len(accounts) and all(a["complete"] for a in accepted)
    sums = {key: sum(float(a["kpis"].get(key) or 0) for a in accepted)
            for key in SUM_FIELDS}
    sums["tacos"] = sums["investment"] / sums["tacosBaseRevenue"] if sums["tacosBaseRevenue"] else None
    sums["roas"] = sums["adsRevenue"] / sums["investment"] if sums["investment"] else None
    sums["acos"] = sums["investment"] / sums["adsRevenue"] if sums["adsRevenue"] else None
    sums["organicRevenue"] = sum(float(a["kpis"].get("organicRevenue") or 0) for a in accepted)
    sums["products"] = sum(len(a["items"]) for a in accepted)
    sums["orders"] = sum(float(i.get("orders") or 0) for a in accepted for i in a["items"])
    sums["price"] = sums["revenue"] / sums["units"] if sums["units"] else None
    sums["adsNoSales"] = sum(float(a["kpis"].get("adsNoSales") or 0) for a in accepted)
    sums["investmentNoAdsSales"] = sum(float(a["kpis"].get("investmentNoAdsSales") or 0) for a in accepted)
    sums["visits"] = sum(float(row.get("visits") or 0) for a in accepted for row in a["daily"]) if accepted and all(a.get("visits_complete") for a in accepted) else None
    sums["cancelledOrders"] = sum(float(a["cancelled_orders"]) for a in accepted) if accepted and all(a.get("cancelled_orders") is not None for a in accepted) else None
    sums["returnsAmount"] = sum(float(a["kpis"].get("returnsAmount") or 0) for a in accepted) if accepted and all(a["kpis"].get("returnsAvailable") is True for a in accepted) else None
    sums["returnsOrdersCount"] = sum(float(a["kpis"].get("returnsOrdersCount") or 0) for a in accepted) if accepted and all(a["kpis"].get("returnsOrdersAvailable") is True for a in accepted) else None
    daily = defaultdict(lambda: {**{key: 0.0 for key in DAILY_FIELDS}, "sources": 0})
    for account in accepted:
        for row in account["daily"]:
            day = str(row.get("date") or "")
            if not start <= day <= end or row.get("partial"):
                continue
            target = daily[day]
            for key in DAILY_FIELDS:
                target[key] += float(row.get(key) or 0)
            target["sources"] += 1
            if row.get("visits") is not None:
                target["visitsSources"] = target.get("visitsSources", 0) + 1
    cursor, last = date.fromisoformat(start), date.fromisoformat(end)
    chart = []
    while cursor <= last:
        day = cursor.isoformat()
        row = daily.get(day)
        if row and row["sources"] == len(accounts):
            chart.append({"date": day, **row, "visits": row["visits"] if row.get("visitsSources") == len(accounts) else None})
        else:
            chart.append({"date": day, "missing": True})
        cursor += timedelta(days=1)
    complete = complete and all(not row.get("missing") for row in chart)
    items = []
    for account in accepted:
        for item in account["items"]:
            items.append({**item, "account": account["label"], "account_id": account["id"]})
    return {"complete": complete, "accepted": len(accepted), "selected": len(accounts),
            "sums": sums, "chart": chart, "items": items}


def _money(value):
    if value is None:
        return "N/D"
    return "R$ " + f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _number(value):
    return "N/D" if value is None else f"{float(value):,.0f}".replace(",", ".")


def _percent(value):
    return "N/D" if value is None else f"{float(value) * 100:.2f}%".replace(".", ",")


def _group_items(items, view):
    groups = {}
    for item in items:
        if view in ("familia", "hibrida") and item.get("familyId"):
            identity = item.get("familyId") or item.get("code") or "sem-familia"
            title = item.get("familyName") or item.get("title") or identity
        elif view in ("variacao", "mlbu") and item.get("userProductId"):
            identity = item["userProductId"]
            title = item.get("userProductName") or item.get("title") or identity
        elif view == "campanha" and item.get("campaignId"):
            identity = item["campaignId"]
            title = item.get("campaignName") or item.get("campaign") or identity
        elif view == "sku" and item.get("sku") and not item.get("skuIsReference"):
            identity = item["sku"]
            title = identity
        else:
            identity = item.get("code") or item.get("sku") or "sem-anuncio"
            title = item.get("title") or identity
        key = (item["account_id"], view, identity)
        if key not in groups:
            groups[key] = {"account": item["account"], "code": identity,
                           "sku": identity if view == "sku" else item.get("sku") or "", "title": title,
                           "totalRevenue": 0.0, "units": 0.0, "orders": 0.0,
                           "investment": 0.0, "adsRevenue": 0.0, "visits": 0.0,
                           "impressions": 0.0, "clicks": 0.0, "members": 0, "visitsKnown": 0}
        for field in ("totalRevenue", "units", "orders", "investment", "adsRevenue"):
            groups[key][field] += float(item.get(field) or 0)
        for field in ("visits", "impressions", "clicks"):
            groups[key][field] += float(item.get(field) or 0)
        groups[key]["members"] += 1
        if item.get("visitsCoverageComplete") is True:
            groups[key]["visitsKnown"] += 1
    return sorted(groups.values(), key=lambda row: -row["totalRevenue"])


def render(accounts, selected_ids, period, projections, failures, view="hibrida", page=1):
    """Independent page: no writes, promotions, or cross-account API calls."""
    from templates import _layout

    modes = (("hibrida", "Híbrida"), ("familia", "Família"),
             ("variacao", "Variação/MLBU"), ("mlb", "MLB"),
             ("sku", "SKU"), ("campanha", "Campanha"))
    view = view if view in dict(modes) else "hibrida"
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
        kpi_rows = [
            ("PRODUTOS ANALISADOS", _number(sums["products"])),
            ("RECEITA TOTAL", _money(sums["revenue"])),
            ("UNIDADES VENDIDAS", _number(sums["units"])),
            ("PEDIDOS POR ITEM", _number(sums["orders"])),
            ("PREÇO MÉDIO POR UNIDADE", _money(sums["price"])),
            ("VISITAS DOS PRODUTOS", _number(sums["visits"])),
            ("VENDAS CANCELADAS", _number(sums["cancelledOrders"])),
            ("DEVOLUÇÕES CONFIRMADAS", _money(sums["returnsAmount"])),
            ("PEDIDOS DEVOLVIDOS", _number(sums["returnsOrdersCount"])),
            ("RECEITA ATRIBUÍDA ADS", _money(sums["adsRevenue"])),
            ("RECEITA ORGÂNICA ESTIMADA", _money(sums["organicRevenue"])),
            ("INVESTIMENTO ADS", _money(sums["investment"])),
            ("BASE TACOS COMERCIAL", _money(sums["tacosBaseRevenue"])),
            ("TACOS GERAL", _percent(sums["tacos"])),
            ("ACOS ADS", _percent(sums["acos"])),
            ("ROAS ADS", "N/D" if sums["roas"] is None else f'{sums["roas"]:.2f}x'.replace(".", ",")),
            ("INVESTIU SEM VENDA ADS", _number(sums["adsNoSales"])),
            ("VALOR SEM VENDA ADS", _money(sums["investmentNoAdsSales"])),
        ]
        metric_keys = ("products", "revenue", "units", "orders", "price", "visits",
                       "cancelledOrders", "returnsAmount", "returnsOrdersCount", "adsRevenue",
                       "organicRevenue", "investment", "tacosBaseRevenue", "tacos", "acos",
                       "roas", "adsNoSales", "investmentNoAdsSales")
        cards = '<div class="cards">' + "".join(
            '<div class="card"><small>{}</small><strong>{}</strong><span class="comparison" data-metric="{}">Comparação N/D — período anterior ainda não certificado nesta visão</span></div>'.format(
                escape(label), escape(value), metric_keys[index]) for index, (label, value) in enumerate(kpi_rows)) + '</div>'
        if overall_complete:
            chart = '<section class="panel"><div class="panel-head"><div><h2>Desempenho diário das contas</h2><small>Dados consolidados das contas selecionadas, dia a dia.</small></div><div class="chart-modes" id="chart-modes"></div></div><div id="daily-chart" class="chart-area"></div></section>'
            chart_data = json.dumps(result["chart"], ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
            chart += '<script type="application/json" id="consolidated-daily">{}</script>'.format(chart_data)
        else:
            chart = '<section class="panel"><h2>Desempenho diário das contas</h2><p>Gráfico N/D: nem todas as contas e datas da seleção estão completas.</p></section>'
        rows = _group_items(result["items"], view)
        table = '<section class="panel"><div class="panel-head"><div><h2>Todos os itens — {} ({})</h2><small>Os mesmos códigos em contas diferentes permanecem separados.</small></div></div>'.format(
            escape(dict(modes)[view]), len(rows))
        table += '<div class="toolbar"><span>VISUALIZAR POR</span><nav class="view-modes" id="view-modes">' + "".join(
            '<a data-view="{}" class="{}" href="?{}">{}</a>'.format(mode,
                'active' if mode == view else '',
                escape(urlencode([("account_id", str(i)) for i in sorted(selected_ids)] + [("view", mode)]), quote=True),
                escape(title)) for mode, title in modes) + '</nav><label>Buscar conta, anúncio ou SKU <input id="item-search" type="search" placeholder="Buscar na seleção"></label></div>'
        table += '<div class="scroll"><table><thead><tr><th>Conta</th><th>Produto / agrupamento</th><th>MLB / SKU</th><th>Receita</th><th>Pedidos</th><th>Unidades</th><th>Investimento</th><th>Receita Ads</th><th>ROAS</th><th>TACOS</th><th>ACOS</th><th>Visitas</th></tr></thead><tbody id="item-rows">'
        page = max(1, min(int(page), max(1, (len(rows) + 99) // 100)))
        for item in rows[(page - 1) * 100:page * 100]:
            revenue = float(item.get("totalRevenue") or 0)
            investment = float(item.get("investment") or 0)
            ads_revenue = float(item.get("adsRevenue") or 0)
            tacos = _percent(investment / revenue) if revenue else "N/D"
            acos = _percent(investment / ads_revenue) if ads_revenue else "N/D"
            roas = f'{ads_revenue/investment:.2f}x'.replace(".", ",") if investment else "N/D"
            table += '<tr><td><b>{}</b></td><td>{}</td><td>{}<br>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                escape(str(item.get("account") or "")), escape(str(item.get("title") or "")),
                escape(str(item.get("code") or "")), escape(str(item.get("sku") or "")),
                escape(_money(revenue)), _number(item.get("orders")), _number(item.get("units")),
                escape(_money(investment)), escape(_money(ads_revenue)), roas, tacos, acos,
                _number(item.get("visits") if item.get("visitsKnown") == item.get("members") else None))
        table += '</tbody></table></div><small id="item-count">Página {} de {} · {} linhas, ordenadas por receita.</small>'.format(
            page, max(1, (len(rows) + 99) // 100), len(rows))
        def page_link(number, title):
            query = [("account_id", str(i)) for i in sorted(selected_ids)]
            query.extend((("view", view), ("page", str(number))))
            return '<a href="?{}">{}</a>'.format(escape(urlencode(query), quote=True), title)
        table += '<nav class="pagination" id="item-pagination">{} {}</nav></section>'.format(page_link(page - 1, "Anterior") if page > 1 else "",
                                             page_link(page + 1, "Próxima") if page * 100 < len(rows) else "")
        item_data = json.dumps(result["items"], ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        table += '<script type="application/json" id="consolidated-items">{}</script>'.format(item_data)
    css = '''<style>
    body{background:#f5f7fb;color:#101828}main{max-width:1440px;margin:0 auto;padding:20px 16px;background:transparent;border:0;border-radius:0;box-shadow:none}
    .accounts{display:flex;flex-wrap:wrap;gap:10px}.account{margin:0;padding:8px;border:1px solid #d9e1ec;border-radius:8px;background:white}.account small{font-weight:normal}
    .chart-modes button,.pagination button{width:auto;margin-top:0}.toolbar input[type=search]{width:100%;padding:10px;border:1px solid #cfd6e4;border-radius:8px}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:9px;margin:18px 0}.card,.panel{background:#fff;border:1px solid #d9e1ec;border-radius:9px;padding:14px}.card{min-height:105px}.card small{display:block;color:#52627a;font-size:10px;font-weight:700;letter-spacing:.4px}.card strong{display:block;font-size:21px;margin:7px 0}.comparison{font-size:11px;color:#667085}.panel{margin:10px 0}.panel h2{font-size:16px;margin:3px 0 8px}.panel-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.panel-head small{color:#667085}.chart-modes,.view-modes{display:flex;flex-wrap:wrap;gap:4px}.chart-modes button,.view-modes a{font-size:11px;border:1px solid #d9e1ec;border-radius:6px;padding:7px 9px;background:#fff;color:#102033;text-decoration:none;cursor:pointer}.chart-modes .active,.view-modes .active{background:#102033;color:#fff}.chart-area{height:290px;display:flex;align-items:flex-end;gap:3px;padding:24px 5px 30px;border-bottom:1px solid #d9e1ec;position:relative}.chart-col{flex:1;height:100%;display:flex;align-items:flex-end;min-width:4px}.chart-bar{width:100%;background:#b5a1ed;border-radius:5px 5px 0 0;min-height:2px}.chart-line{position:absolute;left:5px;right:5px;top:24px;bottom:30px;width:calc(100% - 10px);height:calc(100% - 54px);pointer-events:none}.chart-label{position:absolute;bottom:5px;color:#667085;font-size:10px}.toolbar{margin:16px 0}.toolbar span{font-size:11px;color:#667085;font-weight:700}.toolbar input{display:block;max-width:270px;margin-top:5px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{background:#eef2f7;color:#52627a;text-align:left;font-size:10px}td,th{padding:9px;border-bottom:1px solid #e5eaf1;vertical-align:top}td{white-space:nowrap}td:nth-child(2){white-space:normal;min-width:170px}.pagination{margin:14px 0}.pagination button{margin-right:12px;width:auto}form button{width:auto;margin-top:12px}input[type=checkbox]{width:auto}
    </style>'''
    body = '<h1>Dashboard ADS Mercado Livre — visão consolidada</h1><p>Selecione as contas vinculadas a este cliente. Esta visão é somente leitura e não ocupa um slot ML.</p>'
    body += '<p><a href="/contas">Contas</a> · <a href="/online?confirmed=1">Dashboard individual</a></p>'
    body += '<form method="get" action="/online/consolidado"><input type="hidden" name="selection" value="1"><div class="accounts">{}</div><button type="submit">Atualizar seleção</button></form>'.format(options)
    body += '<p>Período: {} a {} · {} de {} conta(s) com dados da janela exata.</p>'.format(
        escape(period["dateFrom"]), escape(period["dateTo"]), result["accepted"] if result else 0, len(selected))
    script = '''<script>
    (function(){var src=document.getElementById('consolidated-daily');if(!src)return;
      var rows=JSON.parse(src.textContent), area=document.getElementById('daily-chart'), buttons=document.getElementById('chart-modes');
      var metrics=[['revenue','Faturamento'],['adsRevenue','Receita Ads'],['investment','Investimento'],['roas','ROAS'],['tacos','TACOS'],['units','Unidades'],['orders','Pedidos'],['price','Preço médio'],['visits','Visitas']];
      function value(r,k){if(k==='roas')return r.investment>0?r.adsRevenue/r.investment:null;if(k==='tacos')return r.revenue>0?100*r.investment/r.revenue:null;if(k==='price')return r.units>0?r.revenue/r.units:null;return r[k];}
      function draw(k){area.textContent='';var values=rows.map(function(r){return value(r,k)}),valid=values.filter(function(v){return Number.isFinite(v)});
        if(valid.length!==rows.length){area.textContent='N/D — a métrica não tem cobertura comprovada em todas as contas e datas.';return}
        var max=Math.max(1,...valid);
        rows.forEach(function(r,i){var c=document.createElement('div'),b=document.createElement('div'),v=values[i];c.className='chart-col';b.className='chart-bar';b.style.height=Number.isFinite(v)?Math.max(1,v/max*100)+'%':'0';c.title=r.date+': '+(Number.isFinite(v)?v.toLocaleString('pt-BR',{maximumFractionDigits:2}):'N/D');c.appendChild(b);area.appendChild(c)});
        var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 1000 100');svg.setAttribute('preserveAspectRatio','none');svg.classList.add('chart-line');
        var avg=valid.reduce(function(a,b){return a+b},0)/(valid.length||1),line=document.createElementNS('http://www.w3.org/2000/svg','line');
        line.setAttribute('x1','0');line.setAttribute('x2','1000');line.setAttribute('y1',String(100-avg/max*100));line.setAttribute('y2',String(100-avg/max*100));line.setAttribute('stroke','#d97706');line.setAttribute('stroke-dasharray','6 4');svg.appendChild(line);
        var path=document.createElementNS('http://www.w3.org/2000/svg','polyline');path.setAttribute('points',values.map(function(v,i){return (i+.5)*1000/values.length+','+(100-(Number.isFinite(v)?v:0)/max*100)}).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#7651d4');path.setAttribute('stroke-width','2');svg.appendChild(path);area.appendChild(svg);
        var label=document.createElement('span');label.className='chart-label';label.textContent=rows[0].date+' a '+rows[rows.length-1].date+' · média '+avg.toLocaleString('pt-BR',{maximumFractionDigits:2});area.appendChild(label);
        Array.from(buttons.children).forEach(function(b){b.classList.toggle('active',b.dataset.metric===k)})}
      metrics.forEach(function(m){var b=document.createElement('button');b.type='button';b.dataset.metric=m[0];b.textContent=m[1];b.onclick=function(){draw(m[0])};buttons.appendChild(b)});draw('revenue');
    })();
    (function(){var src=document.getElementById('consolidated-items');if(!src)return;
      var items=JSON.parse(src.textContent),body=document.getElementById('item-rows'),count=document.getElementById('item-count'),pager=document.getElementById('item-pagination'),search=document.getElementById('item-search'),modes=document.getElementById('view-modes');
      var mode=(modes.querySelector('.active')||{}).dataset?.view||'hibrida',page=1;
      function num(x){return Number(x)||0}function fmt(x){return num(x).toLocaleString('pt-BR',{maximumFractionDigits:0})}function money(x){return 'R$ '+num(x).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}function pct(x){return x==null?'N/D':(100*x).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+'%'}
      function grouped(){var groups=new Map();items.forEach(function(item){var id=item.code||item.sku||'sem-anuncio',title=item.title||id;
        if((mode==='familia'||mode==='hibrida')&&item.familyId){id=item.familyId;title=item.familyName||title}
        else if((mode==='variacao'||mode==='mlbu')&&item.userProductId){id=item.userProductId;title=item.userProductName||title}
        else if(mode==='campanha'&&item.campaignId){id=item.campaignId;title=item.campaignName||item.campaign||title}
        else if(mode==='sku'&&item.sku&&!item.skuIsReference){id=item.sku;title=id}
        var key=String(item.account_id)+'|'+mode+'|'+id,g=groups.get(key);if(!g){g={account:item.account,code:id,sku:mode==='sku'?id:(item.sku||''),title:title,totalRevenue:0,orders:0,units:0,investment:0,adsRevenue:0,visits:0,members:0,visitsKnown:0};groups.set(key,g)}
        ['totalRevenue','orders','units','investment','adsRevenue','visits'].forEach(function(k){g[k]+=num(item[k])});g.members++;if(item.visitsCoverageComplete===true)g.visitsKnown++});
        return Array.from(groups.values()).sort(function(a,b){return b.totalRevenue-a.totalRevenue})}
      function cell(row,text){var td=document.createElement('td');td.textContent=text;row.appendChild(td)}
      function draw(){var query=search.value.trim().toLocaleLowerCase('pt-BR'),all=grouped().filter(function(r){return !query||[r.account,r.title,r.code,r.sku].some(function(v){return String(v||'').toLocaleLowerCase('pt-BR').includes(query)})});
        var pages=Math.max(1,Math.ceil(all.length/100));page=Math.max(1,Math.min(page,pages));body.textContent='';all.slice((page-1)*100,page*100).forEach(function(g){var tr=document.createElement('tr');
          cell(tr,g.account);cell(tr,g.title);cell(tr,g.code+' / '+g.sku);cell(tr,money(g.totalRevenue));cell(tr,fmt(g.orders));cell(tr,fmt(g.units));cell(tr,money(g.investment));cell(tr,money(g.adsRevenue));cell(tr,g.investment?num(g.adsRevenue/g.investment).toLocaleString('pt-BR',{maximumFractionDigits:2})+'x':'N/D');cell(tr,pct(g.totalRevenue?g.investment/g.totalRevenue:null));cell(tr,pct(g.adsRevenue?g.investment/g.adsRevenue:null));cell(tr,g.visitsKnown===g.members?fmt(g.visits):'N/D');body.appendChild(tr)});
        count.textContent='Página '+page+' de '+pages+' · '+all.length+' linhas, ordenadas por receita.';pager.textContent='';
        if(page>1){var prev=document.createElement('button');prev.type='button';prev.textContent='Anterior';prev.onclick=function(){page--;draw()};pager.appendChild(prev)}
        if(page<pages){var next=document.createElement('button');next.type='button';next.textContent='Próxima';next.onclick=function(){page++;draw()};pager.appendChild(next)}
        Array.from(modes.querySelectorAll('a')).forEach(function(a){a.classList.toggle('active',a.dataset.view===mode)})}
      modes.addEventListener('click',function(e){var a=e.target.closest('a[data-view]');if(!a)return;e.preventDefault();mode=a.dataset.view;page=1;draw()});search.addEventListener('input',function(){page=1;draw()});draw();
    })();</script>'''
    comparison_script = ''
    if overall_complete:
        comparison_data = json.dumps({"accounts": sorted(selected_ids), "period": period,
                                      "current": result["sums"]}, separators=(",", ":")).replace("<", "\\u003c")
        comparison_script = '''<script type="application/json" id="comparison-request">{}</script><script>
        (async function(){{var source=document.getElementById('comparison-request');if(!source)return;
          var config=JSON.parse(source.textContent), previous=[];
          for(var id of config.accounts){{
            var qs=new URLSearchParams({{account_id:String(id),date_from:config.period.dateFrom,date_to:config.period.dateTo}});
            try{{var controller=new AbortController(),timer=setTimeout(function(){{controller.abort()}},45000);
              var response=await fetch('/online/consolidado/comparison?'+qs,{{credentials:'same-origin',signal:controller.signal}});
              clearTimeout(timer);var data=await response.json();if(!response.ok||!data.ok)return;previous.push(data.summary);
            }}catch(error){{return}}
          }}
          function total(key){{return previous.every(function(row){{return typeof row[key]==='number'&&Number.isFinite(row[key])}})
            ?previous.reduce(function(sum,row){{return sum+row[key]}},0):null}}
          var old={{revenue:total('revenue'),units:total('units'),orders:total('orders'),visits:total('visits'),
            returnsAmount:total('returnsAmount'),returnsOrdersCount:total('returnsOrdersCount'),
            adsRevenue:total('adsRevenue'),organicRevenue:total('organicRevenue'),investment:total('investment'),
            tacosBaseRevenue:total('tacosBaseRevenue'),adsNoSales:total('adsNoSales'),
            investmentNoAdsSales:total('investmentNoAdsSales')}};
          old.price=old.revenue!=null&&old.units>0?old.revenue/old.units:null;
          old.tacos=old.investment!=null&&old.tacosBaseRevenue>0?old.investment/old.tacosBaseRevenue:null;
          old.acos=old.investment!=null&&old.adsRevenue>0?old.investment/old.adsRevenue:null;
          old.roas=old.adsRevenue!=null&&old.investment>0?old.adsRevenue/old.investment:null;
          document.querySelectorAll('.comparison[data-metric]').forEach(function(element){{
            var key=element.dataset.metric,now=config.current[key],prior=old[key];
            if(typeof now!=='number'||typeof prior!=='number'||!Number.isFinite(now)||!Number.isFinite(prior))return;
            if(prior===0){{if(now===0)element.textContent='Sem variação vs. período anterior';return}}
            var change=(now-prior)/Math.abs(prior)*100;
            element.textContent=(change>=0?'▲ +':'▼ ')+change.toLocaleString('pt-BR',{{maximumFractionDigits:1}})+'% vs. período anterior';
          }});
        }})();</script>'''.format(comparison_data)
    return _layout("Visão consolidada", body + warning + cards + chart + table + script + comparison_script, css)
