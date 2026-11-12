"""Read-only projections for a user's linked Mercado Livre accounts."""

from collections import defaultdict
from datetime import date, timedelta
from html import escape
import json
from urllib.parse import urlencode, urlparse


SUM_FIELDS = ("revenue", "investment", "adsRevenue", "units", "tacosBaseRevenue")
DAILY_FIELDS = ("revenue", "investment", "adsRevenue", "tacosBaseRevenue", "units", "orders", "visits")
ITEM_FIELDS = ("code", "sku", "skuIsReference", "salesRowPrimary", "globalProductId", "title", "familyId", "familyName", "userProductId",
               "userProductName", "campaign", "campaignId", "campaignName",
               "totalRevenue", "units", "orders", "investment", "adsRevenue",
               "visits", "visitsCoverageComplete", "impressions", "clicks", "thumbnailUrl",
               "lastSaleDate", "lastSalePrice", "currentPrice", "avgSalePrice",
               "priceStatus", "performance7d")


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
                  "returnsOrdersCount", "returnsOrdersAvailable", "returnsObservedPartial",
                  "returnsObservedAmount", "returnsObservedOrdersCount", "adsNoSales",
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
    sums = {key: (sum(float(a["kpis"][key]) for a in accepted)
                  if accepted and all(isinstance(a["kpis"].get(key), (int, float)) for a in accepted) else None)
            for key in SUM_FIELDS}
    sums["tacos"] = sums["investment"] / sums["tacosBaseRevenue"] if sums["investment"] is not None and sums["tacosBaseRevenue"] else None
    sums["roas"] = sums["adsRevenue"] / sums["investment"] if sums["adsRevenue"] is not None and sums["investment"] else None
    sums["acos"] = sums["investment"] / sums["adsRevenue"] if sums["investment"] is not None and sums["adsRevenue"] else None
    def optional_total(key):
        values = [a["kpis"].get(key) for a in accepted]
        return sum(float(value) for value in values) if accepted and all(
            isinstance(value, (int, float)) for value in values) else None

    sums["organicRevenue"] = optional_total("organicRevenue")
    # This counts account-scoped listing records, not distinct global products.
    roots = build_identity_tree([{**item, "account": a["label"], "account_id": a["id"]}
                                 for a in accepted for item in a["items"]])
    sums["products"] = len(roots)
    sums["orders"] = sum(root["orders"] for root in roots) if roots and all(root["orders"] is not None for root in roots) else None
    sums["price"] = sums["revenue"] / sums["units"] if sums["revenue"] is not None and sums["units"] else None
    sums["adsNoSales"] = optional_total("adsNoSales")
    sums["investmentNoAdsSales"] = optional_total("investmentNoAdsSales")
    visit_values = [row.get("visits") for a in accepted for row in a["daily"]]
    sums["visits"] = sum(float(value) for value in visit_values) if accepted and visit_values and all(
        a.get("visits_complete") for a in accepted) and all(
        isinstance(value, (int, float)) for value in visit_values) else None
    sums["cancelledOrders"] = sum(float(a["cancelled_orders"]) for a in accepted) if accepted and all(a.get("cancelled_orders") is not None for a in accepted) else None
    sums["returnsAmount"] = sum(float(a["kpis"].get("returnsAmount")) for a in accepted) if accepted and len(accepted) == len(accounts) and all(a["kpis"].get("returnsAvailable") is True and a["kpis"].get("returnsAmount") is not None for a in accepted) else None
    sums["returnsOrdersCount"] = sum(float(a["kpis"].get("returnsOrdersCount")) for a in accepted) if accepted and len(accepted) == len(accounts) and all(a["kpis"].get("returnsOrdersAvailable") is True and a["kpis"].get("returnsOrdersCount") is not None for a in accepted) else None
    observed_amounts, observed_orders = [], []
    for account in accepted:
        kpis = account["kpis"]
        if kpis.get("returnsAvailable") is True and kpis.get("returnsAmount") is not None:
            observed_amounts.append(float(kpis["returnsAmount"]))
        elif kpis.get("returnsObservedPartial") is True and kpis.get("returnsObservedAmount") is not None:
            observed_amounts.append(float(kpis["returnsObservedAmount"]))
        if kpis.get("returnsOrdersAvailable") is True and kpis.get("returnsOrdersCount") is not None:
            observed_orders.append(float(kpis["returnsOrdersCount"]))
        elif kpis.get("returnsObservedPartial") is True and kpis.get("returnsObservedOrdersCount") is not None:
            observed_orders.append(float(kpis["returnsObservedOrdersCount"]))
    sums["returnsObservedAmount"] = sum(observed_amounts) if observed_amounts else None
    sums["returnsObservedAmountAccounts"] = len(observed_amounts)
    sums["returnsObservedOrdersCount"] = sum(observed_orders) if observed_orders else None
    sums["returnsObservedOrdersAccounts"] = len(observed_orders)
    daily = defaultdict(lambda: {**{key: 0.0 for key in DAILY_FIELDS}, "sources": 0,
                                 "unknown": set()})
    for account in accepted:
        for row in account["daily"]:
            day = str(row.get("date") or "")
            if not start <= day <= end or row.get("partial"):
                continue
            target = daily[day]
            for key in DAILY_FIELDS:
                value = row.get(key)
                if isinstance(value, (int, float)):
                    target[key] += float(value)
                else:
                    target["unknown"].add(key)
            target["sources"] += 1
            if row.get("visits") is not None:
                target["visitsSources"] = target.get("visitsSources", 0) + 1
    cursor, last = date.fromisoformat(start), date.fromisoformat(end)
    chart = []
    while cursor <= last:
        day = cursor.isoformat()
        row = daily.get(day)
        if row and row["sources"] == len(accounts):
            chart.append({"date": day, **{key: (None if key in row["unknown"] else row[key])
                                            for key in DAILY_FIELDS},
                          "visits": row["visits"] if row.get("visitsSources") == len(accounts)
                          and "visits" not in row["unknown"] else None})
        else:
            chart.append({"date": day, "missing": True})
        cursor += timedelta(days=1)
    complete = complete and all(not row.get("missing") and all(
        row.get(key) is not None for key in ("revenue", "investment", "adsRevenue", "units"))
        for row in chart)
    complete = complete and all(sums[key] is not None for key in SUM_FIELDS)
    # The individual cache's KPIs, daily series and listing rows must describe
    # the same selected accounts and window. Never certify a visually plausible
    # aggregate whose hierarchy silently dropped or duplicated a listing.
    reconciliation_issues = []
    for kpi_key, item_key in (("revenue", "totalRevenue"), ("units", "units"),
                              ("investment", "investment"), ("adsRevenue", "adsRevenue")):
        item_values = [root.get(item_key) for root in roots]
        expected_value = sums[kpi_key]
        if expected_value is None or not item_values or any(value is None for value in item_values):
            reconciliation_issues.append("itens_sem_" + kpi_key)
        elif abs(sum(float(value) for value in item_values) - expected_value) > (0.01 if kpi_key in ("revenue", "investment", "adsRevenue") else 0):
            reconciliation_issues.append("itens_divergentes_" + kpi_key)
        daily_values = [row.get(kpi_key) for row in chart]
        if expected_value is None or any(value is None for value in daily_values) or any(row.get("missing") for row in chart):
            reconciliation_issues.append("serie_sem_" + kpi_key)
        elif abs(sum(float(value) for value in daily_values) - expected_value) > (0.01 if kpi_key in ("revenue", "investment", "adsRevenue") else 0):
            reconciliation_issues.append("serie_divergente_" + kpi_key)
    complete = complete and not reconciliation_issues
    items = []
    for account in accepted:
        for item in account["items"]:
            items.append({**item, "account": account["label"], "account_id": account["id"]})
    return {"complete": complete, "reconciliation_issues": reconciliation_issues,
            "accepted": len(accepted), "selected": len(accounts),
            "sums": sums, "chart": chart, "items": items, "roots": roots}


def _money(value):
    if value is None:
        return "N/D"
    return "R$ " + f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _number(value):
    return "N/D" if value is None else f"{float(value):,.0f}".replace(",", ".")


def _percent(value):
    return "N/D" if value is None else f"{float(value) * 100:.2f}%".replace(".", ",")


def _image_url(value):
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def build_identity_tree(items):
    """One server-side hierarchy for initial HTML and every browser interaction.

    A last-sale SKU is only an association of listings, never a certified
    attribution of the listing's entire revenue to that SKU.
    """
    fields = ("totalRevenue", "orders", "units", "investment", "adsRevenue", "visits")

    def node(level, key, title, *, account="", account_id=None, confidence=""):
        return {"level": level, "key": key, "title": title, "account": account,
                "account_id": account_id, "confidence": confidence,
                "children": [], "sources": [], "thumbnailUrl": "",
                "lastSaleDate": "", "lastSalePrice": None, "currentPrice": None,
                "priceMin": None, "priceMax": None, "avgSalePrice": None,
                "performance7d": {},
                **{field: None for field in fields}}

    def get_child(parent, level, key, title, **kwargs):
        for child in parent["children"]:
            if child["key"] == key:
                return child
        child = node(level, key, title, **kwargs)
        parent["children"].append(child)
        return child

    roots = []
    roots_by_key = {}
    # One listing can carry several Ads campaigns; sales are counted once.
    # Duplicate campaign rows contribute Ads only once per campaign identity.
    listings = {}
    for item in items:
        account_id = int(item["account_id"])
        code = str(item.get("code") or "").strip().upper()
        if not code.startswith("MLB"):
            continue
        key = (account_id, code)
        previous = listings.get(key)
        if previous is None:
            campaign_id = str(item.get("campaignId") or "")
            listings[key] = {**item, "_campaigns": {campaign_id},
                             "_campaign_data": {campaign_id: {
                                 "title": str(item.get("campaignName") or item.get("campaign") or "Sem campanha identificada"),
                                 "investment": item.get("investment"), "adsRevenue": item.get("adsRevenue")}}}
            continue
        campaign = str(item.get("campaignId") or "")
        if campaign in previous["_campaigns"]:
            for field in ("investment", "adsRevenue"):
                if previous["_campaign_data"][campaign].get(field) != item.get(field):
                    previous["_campaign_data"][campaign][field] = None
        else:
            previous["_campaigns"].add(campaign)
            previous["_campaign_data"][campaign] = {
                "title": str(item.get("campaignName") or item.get("campaign") or "Sem campanha identificada"),
                "investment": item.get("investment"), "adsRevenue": item.get("adsRevenue")}
        for field in ("investment", "adsRevenue"):
            campaign_values = [row.get(field) for row in previous["_campaign_data"].values()]
            previous[field] = (sum(float(value) for value in campaign_values)
                               if all(value is not None for value in campaign_values) else None)
        # The online cache assigns sales to the first row of an MLB and zeros
        # subsequent campaign rows. Only that explicitly marked row is the
        # sales receipt; a conflict between two primary rows remains unknown.
        for field in ("totalRevenue", "orders", "units"):
            if previous.get("salesRowPrimary") is True and item.get("salesRowPrimary") is False:
                continue
            if previous.get("salesRowPrimary") is False and item.get("salesRowPrimary") is True:
                previous[field] = item.get(field)
            elif previous.get(field) != item.get(field):
                previous[field] = None
        if item.get("salesRowPrimary") is True:
            previous["salesRowPrimary"] = True

    for item in listings.values():
        account_id = int(item["account_id"])
        code = str(item["code"]).upper()
        sku = str(item.get("sku") or "").strip()
        global_id = str(item.get("globalProductId") or "").strip()
        if sku and item.get("skuIsReference") is not True and global_id:
            root_key = "product:" + global_id
            root_title = "Produto comprovado " + sku
            confidence = "global_product_id"
        elif sku and item.get("skuIsReference") is not True:
            root_key = "declared_association:" + sku.casefold()
            root_title = "Anúncios associados ao SKU declarado " + sku
            confidence = "sku_text_unverified"
        elif sku:
            root_key = "reference:" + sku.casefold()
            root_title = "Anúncios associados ao SKU de referência " + sku
            confidence = "last_sale_reference"
        else:
            root_key = f"unidentified:{account_id}:{code}"
            root_title = item.get("title") or code
            confidence = "listing_only"
        root = roots_by_key.get(root_key)
        if root is None:
            root = node("global", root_key, root_title, confidence=confidence)
            roots.append(root)
            roots_by_key[root_key] = root
        account = str(item.get("account") or account_id)
        account_node = get_child(root, "account", f"account:{account_id}", account,
                                 account=account, account_id=account_id)
        family_id = str(item.get("familyId") or "").strip()
        family_name = str(item.get("familyName") or "").strip()
        parent = get_child(account_node, "family", "family:" + (family_id or family_name or code),
                           family_name or family_id or "Família não cadastrada", account=account,
                           account_id=account_id)
        mlbu_id = str(item.get("userProductId") or "").strip()
        mlbu_name = str(item.get("userProductName") or "").strip()
        parent = get_child(parent, "mlbu", "mlbu:" + (mlbu_id or mlbu_name or code),
                           mlbu_name or mlbu_id or "MLBU não cadastrado", account=account,
                           account_id=account_id)
        leaf = get_child(parent, "mlb", "mlb:" + code, str(item.get("title") or code),
                         account=account, account_id=account_id)
        leaf.update({field: item.get(field) for field in fields})
        leaf["code"] = code
        leaf["sku"] = sku
        leaf["skuIsReference"] = item.get("skuIsReference") is True
        leaf["thumbnailUrl"] = _image_url(item.get("thumbnailUrl"))
        leaf["sources"] = [{"account_id": account_id, "account": account, "codes": [code]}]
        leaf["visitsKnown"] = item.get("visitsCoverageComplete") is True
        leaf["lastSaleDate"] = str(item.get("lastSaleDate") or "")
        leaf["lastSalePrice"] = item.get("lastSalePrice") if (item.get("lastSalePrice") or 0) > 0 else None
        leaf["currentPrice"] = item.get("currentPrice") if (item.get("currentPrice") or 0) > 0 else None
        leaf["priceMin"] = leaf["priceMax"] = leaf["currentPrice"]
        leaf["avgSalePrice"] = (float(leaf["totalRevenue"]) / float(leaf["units"])
                                if leaf["totalRevenue"] is not None and leaf["units"] else None)
        leaf["priceStatus"] = item.get("priceStatus") or ""
        leaf["performance7d"] = item.get("performance7d") if isinstance(item.get("performance7d"), dict) else {}
        for campaign_id, campaign_data in item["_campaign_data"].items():
            if not campaign_id:
                continue
            campaign_node = get_child(leaf, "campaign", "campaign:" + (campaign_id or "none"),
                                      campaign_data["title"], account=account, account_id=account_id)
            campaign_node["investment"] = campaign_data["investment"]
            campaign_node["adsRevenue"] = campaign_data["adsRevenue"]
            campaign_node["sources"] = [{"account_id": account_id, "account": account, "codes": [code]}]

    def finish(current):
        for child in current["children"]:
            finish(child)
        if current["children"] and current["level"] != "mlb":
            for field in fields:
                values = [child.get(field) for child in current["children"]]
                current[field] = sum(float(value) for value in values) if all(value is not None for value in values) else None
            sources = {}
            for child in current["children"]:
                for source in child["sources"]:
                    target = sources.setdefault(source["account_id"], {"account_id": source["account_id"],
                                                                       "account": source["account"], "codes": []})
                    for code in source["codes"]:
                        if code not in target["codes"]:
                            target["codes"].append(code)
            current["sources"] = list(sources.values())
            current["thumbnailUrl"] = next((child["thumbnailUrl"] for child in current["children"]
                                           if child["thumbnailUrl"]), "")
            current["visitsKnown"] = all(child.get("visitsKnown") is True for child in current["children"])
            current["avgSalePrice"] = (current["totalRevenue"] / current["units"]
                                        if current["totalRevenue"] is not None and current["units"] else None)
            prices = [child.get("priceMin") for child in current["children"]]
            price_maxes = [child.get("priceMax") for child in current["children"]]
            if all(isinstance(value, (int, float)) and value > 0 for value in prices + price_maxes):
                current["priceMin"], current["priceMax"] = min(prices), max(price_maxes)
                if current["priceMin"] == current["priceMax"]:
                    current["currentPrice"] = current["priceMin"]
            dated = [child for child in current["children"] if child.get("lastSaleDate")]
            if dated:
                current["lastSaleDate"] = max(child["lastSaleDate"] for child in dated)
                latest_prices = {child.get("lastSalePrice") for child in dated
                                 if child["lastSaleDate"] == current["lastSaleDate"]}
                if len(latest_prices) == 1:
                    current["lastSalePrice"] = latest_prices.pop()
            performances = [child.get("performance7d") or {} for child in current["children"]]
            window_keys = ("date_from", "previous_to", "current_from", "date_to")
            if performances and all(p.get("date_to") and all(p.get(k) == performances[0].get(k)
                                   for k in window_keys) for p in performances):
                current["performance7d"] = {key: performances[0][key] for key in window_keys}
                for metric in ("sales", "visits"):
                    values = [p.get(metric) for p in performances]
                    if all(isinstance(value, dict) and value.get("complete") is True
                           and all(isinstance(value.get(side), (int, float)) for side in ("current", "previous"))
                           for value in values):
                        current["performance7d"][metric] = {
                            "complete": True,
                            "current": sum(value["current"] for value in values),
                            "previous": sum(value["previous"] for value in values),
                        }
        current["accountCount"] = len(current["sources"])
        current["children"].sort(key=lambda child: -(child.get("totalRevenue") or 0))

    for root in roots:
        finish(root)
    return sorted(roots, key=lambda root: -(root.get("totalRevenue") or 0))


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
        reasons = ", ".join(result["reconciliation_issues"]) if result and result["reconciliation_issues"] else ""
        warning = '<div class="alert err">Visão incompleta: {}. Os totais consolidados não são apresentados como completos.</div>'.format(
            "falha em " + names if names else ("divergência entre fontes: " + escape(reasons) if reasons else "há dias ou contas sem certificação"))
    cards = chart = table = reconciliation = ""
    if result:
        sums = result["sums"]
        by_id = {account["id"]: account for account in projections}
        reconciliation = '<section class="panel"><h2>Conferência por conta</h2><small>Mesma janela e mesma leitura usada nos painéis individuais. Não substitui a conferência com o Mercado Livre.</small><div class="scroll"><table><thead><tr><th>Conta</th><th>Período</th><th>Receita</th><th>Unidades</th><th>Pedidos por item</th><th>Investimento Ads</th><th>Receita Ads</th><th>Cancelamentos</th><th>Devoluções confirmadas</th><th>Situação</th></tr></thead><tbody>'
        account_orders = defaultdict(list)
        for root in result["roots"]:
            for account_node in root["children"]:
                account_orders[account_node["account_id"]].append(account_node.get("orders"))
        for link in selected:
            account = by_id.get(int(link["id"]))
            exact = bool(account and account["period"] == (period["dateFrom"], period["dateTo"]))
            certified = exact and account["complete"]
            label = str(link["official_store"] or link["nickname"] or link["client_id"])
            orders = account_orders.get(int(link["id"]), [])
            orders_total = sum(orders) if orders and all(value is not None for value in orders) else None
            reconciliation += '<tr><td>{}</td><td>{} a {}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                escape(label), escape(period["dateFrom"]), escape(period["dateTo"]),
                escape(_money(account["kpis"].get("revenue"))) if certified else "N/D",
                escape(_number(account["kpis"].get("units"))) if certified else "N/D",
                escape(_number(orders_total)) if certified else "N/D",
                escape(_money(account["kpis"].get("investment"))) if certified else "N/D",
                escape(_money(account["kpis"].get("adsRevenue"))) if certified else "N/D",
                escape(_number(account.get("cancelled_orders"))) if certified else "N/D",
                escape(_money(account["kpis"].get("returnsAmount"))) if certified and account["kpis"].get("returnsAvailable") is True else "N/D",
                "Completa" if certified else "Não certificada")
        reconciliation += '</tbody><tfoot><tr><th>Soma das contas selecionadas</th><th>{} a {}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr></tfoot></table></div></section>'.format(
            escape(period["dateFrom"]), escape(period["dateTo"]),
            escape(_money(sums["revenue"])) if overall_complete else "N/D",
            escape(_number(sums["units"])) if overall_complete else "N/D",
            escape(_number(sums["orders"])) if overall_complete else "N/D",
            escape(_money(sums["investment"])) if overall_complete else "N/D",
            escape(_money(sums["adsRevenue"])) if overall_complete else "N/D",
            escape(_number(sums["cancelledOrders"])) if overall_complete else "N/D",
            escape(_money(sums["returnsAmount"])) if overall_complete else "N/D",
            "Completa" if overall_complete else "Não certificada")
        if overall_complete:
            kpi_rows = [
            ("AGRUPAMENTOS ANALISADOS", _number(sums["products"])),
            ("RECEITA TOTAL", _money(sums["revenue"])),
            ("UNIDADES VENDIDAS", _number(sums["units"])),
            ("PEDIDOS POR ITEM", _number(sums["orders"])),
            ("PREÇO MÉDIO POR UNIDADE", _money(sums["price"])),
            ("VISITAS DOS PRODUTOS", _number(sums["visits"])),
            ("VENDAS CANCELADAS", _number(sums["cancelledOrders"])),
            (("DEVOLUÇÕES CONFIRMADAS" if sums["returnsAmount"] is not None or sums["returnsObservedAmount"] is None else
              "DEVOLUÇÕES OBSERVADAS (PARCIAL, {}/{} CONTAS; NÃO É TOTAL)".format(sums["returnsObservedAmountAccounts"], len(selected))),
             _money(sums["returnsAmount"] if sums["returnsAmount"] is not None else sums["returnsObservedAmount"])),
            (("PEDIDOS DEVOLVIDOS" if sums["returnsOrdersCount"] is not None or sums["returnsObservedOrdersCount"] is None else
              "PEDIDOS DEVOLVIDOS OBSERVADOS (PARCIAL, {}/{} CONTAS; NÃO É TOTAL)".format(sums["returnsObservedOrdersAccounts"], len(selected))),
             _number(sums["returnsOrdersCount"] if sums["returnsOrdersCount"] is not None else sums["returnsObservedOrdersCount"])),
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
        else:
            kpi_rows = []
        metric_keys = ("products", "revenue", "units", "orders", "price", "visits",
                       "cancelledOrders", "returnsAmount", "returnsOrdersCount", "adsRevenue",
                       "organicRevenue", "investment", "tacosBaseRevenue", "tacos", "acos",
                       "roas", "adsNoSales", "investmentNoAdsSales")
        cards = '<div class="cards">' + "".join(
            '<div class="card"><small>{}</small><strong>{}</strong>{}</div>'.format(
                escape(label), escape(value),
                '' if metric_keys[index] == 'products' else '<span class="comparison" data-metric="{}">Comparação N/D — período anterior ainda não certificado nesta visão</span>'.format(metric_keys[index]))
            for index, (label, value) in enumerate(kpi_rows)) + '</div>'
        if overall_complete:
            chart = '<section class="panel"><div class="panel-head"><div><h2>Desempenho diário das contas</h2><small id="chart-summary">Dados consolidados das contas selecionadas, dia a dia.</small></div><div class="chart-modes" id="chart-modes"></div></div><div class="chart-shell"><div id="daily-chart" class="chart-area"></div><div id="chart-tooltip" class="chart-tooltip" hidden></div></div></section>'
            chart_data = json.dumps(result["chart"], ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
            chart += '<script type="application/json" id="consolidated-daily">{}</script>'.format(chart_data)
        else:
            chart = '<section class="panel"><h2>Desempenho diário das contas</h2><p>Gráfico N/D: nem todas as contas e datas da seleção estão completas.</p></section>'
        roots = result["roots"] if overall_complete else []
        table = '<section class="panel"><div class="panel-head"><div><h2>Todos os itens — {} ({})</h2><small>Produto/SKU global → conta → família → variação/MLBU → MLB. SKU de referência associa anúncios; não atribui a receita inteira ao SKU.</small></div></div>'.format(
            escape(dict(modes)[view]), len(roots))
        table += '<div class="toolbar"><span>VISUALIZAR POR</span><nav class="view-modes" id="view-modes">' + "".join(
            '<a data-view="{}" class="{}" href="?{}">{}</a>'.format(mode,
                'active' if mode == view else '',
                escape(urlencode([("account_id", str(i)) for i in sorted(selected_ids)] + [
                    ("view", mode), ("period", period.get("mode") or "30d"),
                    ("date_from", period["dateFrom"]), ("date_to", period["dateTo"])]), quote=True),
                escape(title)) for mode, title in modes) + '</nav><label>Buscar conta, anúncio ou SKU <input id="item-search" type="search" placeholder="Buscar na seleção"></label></div>'
        table += '<div class="scroll hierarchy-scroll" role="region" aria-label="Tabela de produtos; deslize horizontalmente para ver todas as métricas"><table class="item-table"><thead><tr><th>Produto / agrupamento</th><th>Conta</th><th>MLB / SKU</th><th>Preço atual / médio / última venda</th><th>Última venda</th><th>Receita</th><th>Pedidos por item</th><th>Unidades</th><th>Investimento</th><th>Receita Ads</th><th>ROAS</th><th>TACOS</th><th>ACOS</th><th>Visitas</th><th>Últimos 7 dias</th><th>Detalhe</th></tr></thead><tbody id="item-rows">'
        page = max(1, min(int(page), max(1, (len(roots) + 99) // 100)))
        table += '</tbody></table></div><small id="item-count">Página {} de {} · {} agrupamentos, ordenados por receita.</small>'.format(
            page, max(1, (len(roots) + 99) // 100), len(roots))
        def page_link(number, title):
            query = [("account_id", str(i)) for i in sorted(selected_ids)]
            query.extend((("view", view), ("page", str(number)), ("period", period.get("mode") or "30d")))
            if period.get("mode") == "custom":
                query.extend((("date_from", period["dateFrom"]), ("date_to", period["dateTo"])))
            return '<a href="?{}">{}</a>'.format(escape(urlencode(query), quote=True), title)
        table += '<nav class="pagination" id="item-pagination">{} {}</nav></section>'.format(page_link(page - 1, "Anterior") if page > 1 else "",
                                             page_link(page + 1, "Próxima") if page * 100 < len(roots) else "")
        item_data = json.dumps(roots, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        table += '<script type="application/json" id="consolidated-items">{}</script>'.format(item_data)
        table += '<script type="application/json" id="consolidated-period">{}</script>'.format(
            json.dumps({"dateFrom": period["dateFrom"], "dateTo": period["dateTo"]}))
        table += '<div class="detail-backdrop" id="detail-backdrop" hidden><section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title"><header><div><h2 id="detail-title"></h2><small id="detail-account"></small></div><button type="button" id="detail-close" aria-label="Fechar">×</button></header><div class="detail-content"><div class="detail-summary" id="detail-summary"></div><section class="panel"><div class="panel-head"><div><h3>Desempenho diário do produto</h3><div id="detail-status">Selecione um produto.</div></div><div class="chart-modes" id="detail-chart-modes"></div></div><div class="chart-shell"><div class="detail-chart" id="detail-chart"></div><div class="chart-tooltip" id="detail-tooltip" hidden></div></div></section></div></section></div>'
    css = '''<style>
    body{background:#f5f7fb;color:#101828}main{max-width:1440px;margin:0 auto;padding:20px 16px;background:transparent;border:0;border-radius:0;box-shadow:none}
    .accounts{display:flex;flex-wrap:wrap;gap:10px}.account{margin:0;padding:8px;border:1px solid #d9e1ec;border-radius:8px;background:white}.account small{font-weight:normal}.period-picker{display:flex;flex-wrap:wrap;align-items:end;gap:10px;margin:12px 0}.period-picker label{margin:0}.period-picker select,.period-picker input{display:block;width:auto;min-width:140px;padding:9px;border:1px solid #cfd6e4;border-radius:8px;background:#fff}.period-picker button{margin:0}
    .chart-modes button,.pagination button{width:auto;margin-top:0}.toolbar input[type=search]{width:100%;padding:10px;border:1px solid #cfd6e4;border-radius:8px}.detail-backdrop[hidden]{display:none}.detail-backdrop{position:fixed;inset:0;background:#10182899;z-index:100;display:grid;place-items:center;padding:15px}.detail-modal{width:min(1050px,96vw);max-height:90vh;overflow:auto;background:#f5f7fb;border-radius:12px}.detail-modal header{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;background:#fff;border-bottom:1px solid #d9e1ec}.detail-modal header h2{margin:0;font-size:18px}.detail-modal header small{color:#667085}.detail-modal header button{width:auto;margin:0;background:#fff;color:#102033;border:1px solid #d9e1ec}.detail-content{padding:18px}.detail-chart{height:210px;display:flex;align-items:end;gap:3px;background:#fff;border:1px solid #d9e1ec;border-radius:8px;padding:16px}.detail-chart span{flex:1;min-width:2px;background:#b5a1ed;border-radius:4px 4px 0 0}.detail-summary{margin-top:15px;display:flex;gap:10px;flex-wrap:wrap}.detail-summary span{padding:10px;border:1px solid #d9e1ec;border-radius:8px;background:#fff}
    .detail-chart{height:auto;display:block;min-height:48px;border:0;padding:0}.detail-chart svg{display:block;width:100%;height:300px}.detail-summary{margin:0 0 15px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.detail-summary span{font-size:12px}.detail-content .panel h3{margin:3px 0 8px;font-size:16px}@media(max-width:700px){.detail-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
    .cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin:18px 0}.card,.panel{background:#fff;border:1px solid #d9e1ec;border-radius:9px;padding:14px}.card{min-height:105px}.card small{display:block;color:#52627a;font-size:10px;font-weight:700;letter-spacing:.4px}.card strong{display:block;font-size:21px;margin:7px 0}.comparison{font-size:11px;color:#667085}.panel{margin:10px 0}.panel h2{font-size:16px;margin:3px 0 8px}.panel-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.panel-head small{color:#667085}.chart-modes,.view-modes{display:flex;flex-wrap:wrap;gap:4px}.chart-modes button,.view-modes a{font-size:11px;border:1px solid #d9e1ec;border-radius:6px;padding:7px 9px;background:#fff;color:#102033;text-decoration:none;cursor:pointer}.chart-modes .active,.view-modes .active{background:#102033;color:#fff}.chart-shell{position:relative;margin-top:10px;border:1px solid #d9e1ec;border-radius:10px;background:#fff}.chart-area{min-height:320px}.chart-area svg{display:block;width:100%;height:320px}.chart-grid{stroke:#e4e7ec;stroke-width:1;stroke-dasharray:4 5}.chart-axis{fill:#667085;font-size:11px}.chart-hover-line{stroke:#a29ab8;stroke-dasharray:4 4;visibility:hidden}.chart-hit{fill:transparent;cursor:crosshair}.chart-hit:hover+.chart-hover-line{visibility:visible}.chart-tooltip{position:absolute;z-index:4;min-width:195px;padding:10px 12px;border:1px solid #d0d5dd;border-radius:10px;background:#fff;box-shadow:0 12px 26px #1018282e;font-size:11px;pointer-events:none}.chart-tooltip[hidden],.hierarchy-child-row[hidden]{display:none}.chart-tooltip b{display:block;margin-bottom:5px}.chart-tooltip div{display:flex;justify-content:space-between;gap:15px}.toolbar{margin:16px 0}.toolbar span{font-size:11px;color:#667085;font-weight:700}.toolbar input{display:block;max-width:270px;margin-top:5px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{background:#eef2f7;color:#52627a;text-align:left;font-size:10px}td,th{padding:9px;border-bottom:1px solid #e5eaf1;vertical-align:top}td{white-space:nowrap}td:first-child{white-space:normal;min-width:220px}.product-name{display:flex;align-items:center;gap:9px}.product-photo{width:44px;height:44px;object-fit:contain;border:1px solid #d9e1ec;border-radius:6px;flex:none}.product-photo.empty{display:grid;place-items:center;background:#f1f4f8;color:#667085;font-size:9px}.detail-open,.hierarchy-toggle{width:auto;margin:0;padding:7px 10px;background:#fff;color:#102033;border:1px solid #d9e1ec}.hierarchy-toggle{font-weight:700;min-width:30px}.hierarchy-child-row>td{padding:12px 18px;background:#f8faff}.hierarchy-child-row td:first-child{min-width:0}.hierarchy-group{margin:0 0 12px}.hierarchy-group h3{font-size:12px;margin:8px 0}.hierarchy-table td,.hierarchy-table th{white-space:normal;min-width:0}.hierarchy-table td:first-child{min-width:160px}.pagination{margin:14px 0}.pagination button{margin-right:12px;width:auto}form button{width:auto}input[type=checkbox]{width:auto}@media(max-width:1100px){.cards{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}}
    .hierarchy-scroll{max-width:100%;border:1px solid #d9e1ec;border-radius:8px}.item-table{min-width:1920px}.item-table th{position:sticky;top:0;z-index:1}.item-table td:first-child{min-width:280px;max-width:320px}.item-table td{white-space:normal;min-width:78px}.item-table td:nth-child(4),.item-table td:nth-child(15){min-width:160px}.hierarchy-row.level-global{background:#e9f1ff;font-weight:700}.hierarchy-row.level-account{background:#f0f5ff}.hierarchy-row.level-family{background:#faf1ff}.hierarchy-row.level-mlbu{background:#fff7e8}.hierarchy-row.level-mlb{background:#f0faf6}.hierarchy-row.level-campaign{background:#f8fafc}.hierarchy-row td:first-child{border-left:4px solid #4d75b9}.hierarchy-row.level-family td:first-child{border-left-color:#aa75c8}.hierarchy-row.level-mlbu td:first-child{border-left-color:#b7872e}.hierarchy-row.level-mlb td:first-child{border-left-color:#23836b}.hierarchy-row small{display:block;color:#667085;font-size:10px;font-weight:normal}.hierarchy-row .product-name{align-items:flex-start}.hierarchy-row .detail-open{white-space:nowrap}.hierarchy-hint{font-size:11px;color:#667085;margin:7px 0 0}@media(max-width:700px){.hierarchy-scroll{margin-right:-14px}.item-table{min-width:1920px}}
    </style>'''
    body = '<h1>Dashboard ADS Mercado Livre — visão consolidada</h1><p>Selecione as contas vinculadas a este cliente. Esta visão é somente leitura e não ocupa um slot ML.</p>'
    body += '<p><a href="/contas">Contas</a> · <a href="/online?confirmed=1">Dashboard individual</a></p>'
    period_options = "".join('<option value="{}" {}>{}</option>'.format(mode, "selected" if period.get("mode") == mode else "", label)
                             for mode, label in (("7d", "Últimos 7 dias"), ("15d", "Últimos 15 dias"),
                                                 ("30d", "Últimos 30 dias"), ("custom", "Personalizado")))
    body += '<form method="get" action="/online/consolidado"><input type="hidden" name="selection" value="1"><div class="accounts">{}</div><div class="period-picker"><label>Período <select name="period">{}</select></label><label>De <input name="date_from" type="date" value="{}"></label><label>Até <input name="date_to" type="date" value="{}"></label><button type="submit">Atualizar visão</button></div></form>'.format(
        options, period_options, escape(period["dateFrom"], quote=True), escape(period["dateTo"], quote=True))
    body += '<p>Período: {} a {} · {} de {} conta(s) com dados da janela exata.</p>'.format(
        escape(period["dateFrom"]), escape(period["dateTo"]), result["accepted"] if result else 0, len(selected))
    script = '''<script>
    (function(){var src=document.getElementById('consolidated-daily');if(!src)return;
      var rows=JSON.parse(src.textContent), area=document.getElementById('daily-chart'), buttons=document.getElementById('chart-modes');
      var metrics=[['revenue','Faturamento'],['adsRevenue','Receita Ads'],['investment','Investimento'],['roas','ROAS'],['tacos','TACOS'],['units','Unidades'],['orders','Pedidos'],['price','Preço médio'],['visits','Visitas']];
      function value(r,k){if(k==='roas')return r.investment>0?r.adsRevenue/r.investment:null;if(k==='tacos')return r.tacosBaseRevenue>0?r.investment/r.tacosBaseRevenue:null;if(k==='price')return r.units>0?r.revenue/r.units:null;return r[k];}
      var ns='http://www.w3.org/2000/svg',tip=document.getElementById('chart-tooltip'),summary=document.getElementById('chart-summary');
      function svgEl(tag,attrs,parent){var el=document.createElementNS(ns,tag);Object.keys(attrs).forEach(function(key){el.setAttribute(key,attrs[key])});parent.appendChild(el);return el}
      function fmt(v,k){if(v==null||!Number.isFinite(v))return 'N/D';if(['revenue','adsRevenue','investment','price'].includes(k))return v.toLocaleString('pt-BR',{style:'currency',currency:'BRL'});if(k==='tacos')return (v*100).toLocaleString('pt-BR',{maximumFractionDigits:2})+'%';if(k==='roas')return v.toLocaleString('pt-BR',{maximumFractionDigits:2})+'x';return v.toLocaleString('pt-BR',{maximumFractionDigits:0})}
      function showTip(row,k,index,svg){tip.textContent='';var heading=document.createElement('b');heading.textContent=new Date(row.date+'T12:00:00').toLocaleDateString('pt-BR',{day:'numeric',month:'short',year:'numeric'});tip.appendChild(heading);
        metrics.forEach(function(m){var line=document.createElement('div'),a=document.createElement('span'),b=document.createElement('strong');a.textContent=m[1];b.textContent=fmt(value(row,m[0]),m[0]);line.append(a,b);if(m[0]===k)line.style.color='#175cd3';tip.appendChild(line)});
        tip.hidden=false;var x=(index+.5)*svg.clientWidth/rows.length;tip.style.left=Math.max(105,Math.min(svg.clientWidth-105,x))+'px';tip.style.top='9px';tip.style.transform='translateX(-50%)'}
      function draw(k){area.textContent='';tip.hidden=true;var values=rows.map(function(r){return value(r,k)}),valid=values.filter(function(v){return Number.isFinite(v)});
        Array.from(buttons.children).forEach(function(b){b.classList.toggle('active',b.dataset.metric===k)});
        if(!rows.length||!valid.length||(['visits'].includes(k)&&valid.length!==rows.length)){area.textContent='N/D — a métrica não tem cobertura comprovada em todas as contas e datas.';summary.textContent='Média e tendência omitidas quando falta cobertura.';return}
        var avg=valid.reduce(function(a,b){return a+b},0)/valid.length;
        if(k==='roas'){var spend=rows.reduce(function(a,r){return a+r.investment},0);avg=spend>0?rows.reduce(function(a,r){return a+r.adsRevenue},0)/spend:avg}
        if(k==='tacos'){var base=rows.reduce(function(a,r){return a+r.tacosBaseRevenue},0);avg=base>0?rows.reduce(function(a,r){return a+r.investment},0)/base:avg}
        var max=Math.max(0.01,...valid,avg)*1.12,width=1040,height=320,left=82,right=26,top=44,bottom=50,plotW=width-left-right,plotH=height-top-bottom;
        summary.textContent=metrics.find(function(m){return m[0]===k})[1]+' por dia. Média do período: '+fmt(avg,k)+'.';
        var svg=svgEl('svg',{viewBox:'0 0 '+width+' '+height,role:'img','aria-label':metrics.find(function(m){return m[0]===k})[1]+' por dia'},area),x=function(i){return left+(i+.5)*plotW/rows.length},y=function(v){return top+plotH-v/max*plotH};
        for(var t=0;t<=4;t++){var amount=max*t/4,yy=y(amount);svgEl('line',{x1:left,y1:yy,x2:width-right,y2:yy,class:'chart-grid'},svg);var tick=svgEl('text',{x:left-10,y:yy+4,'text-anchor':'end',class:'chart-axis'},svg);tick.textContent=fmt(amount,k)}
        var meanY=y(avg);svgEl('line',{x1:left,y1:meanY,x2:width-right,y2:meanY,stroke:'#f59e0b','stroke-width':2,'stroke-dasharray':'7 5'},svg);var mean=svgEl('text',{x:width-right,y:24,'text-anchor':'end',fill:'#b45309','font-size':13,'font-weight':700},svg);mean.textContent='Média do período '+fmt(avg,k);
        var lineOnly=['roas','tacos','price'].includes(k),step=plotW/rows.length,barWidth=Math.min(28,step*.65),points=[];
        rows.forEach(function(row,i){var xx=x(i),v=values[i];if(!lineOnly&&Number.isFinite(v))svgEl('rect',{x:xx-barWidth/2,y:y(v),width:barWidth,height:Math.max(0,top+plotH-y(v)),rx:Math.min(6,barWidth/3),fill:'#a98de8','fill-opacity':'.65'},svg);
          var neighbors=values.slice(Math.max(0,i-1),Math.min(values.length,i+2)).filter(function(n){return Number.isFinite(n)}),smooth=lineOnly?v:neighbors.reduce(function(a,b){return a+b},0)/neighbors.length;points.push(Number.isFinite(smooth)?xx+','+y(smooth):null);
          if(i%Math.max(1,Math.ceil(rows.length/9))===0||i===rows.length-1){var label=svgEl('text',{x:xx,y:height-15,'text-anchor':'middle',class:'chart-axis'},svg);label.textContent=new Date(row.date+'T12:00:00').toLocaleDateString('pt-BR',{day:'numeric',month:'short'})}});
        var segment=[];function plotSegment(){if(segment.length>1)svgEl('polyline',{points:segment.join(' '),fill:'none',stroke:'#7651d4','stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},svg);segment=[]}
        points.forEach(function(point){if(point)segment.push(point);else plotSegment()});plotSegment();
        rows.forEach(function(row,i){var xx=x(i),hit=svgEl('g',{},svg),rect=svgEl('rect',{x:xx-step/2,y:top,width:step,height:plotH,class:'chart-hit'},hit);svgEl('line',{x1:xx,y1:top,x2:xx,y2:top+plotH,class:'chart-hover-line'},hit);rect.addEventListener('pointerenter',function(){showTip(row,k,i,svg)});rect.addEventListener('pointermove',function(){showTip(row,k,i,svg)});rect.addEventListener('pointerleave',function(){tip.hidden=true})})}
      metrics.forEach(function(m){var b=document.createElement('button');b.type='button';b.dataset.metric=m[0];b.textContent=m[1];b.onclick=function(){draw(m[0])};buttons.appendChild(b)});draw('revenue');
    })();
    (function(){var src=document.getElementById('consolidated-items');if(!src)return;
      var roots=JSON.parse(src.textContent),body=document.getElementById('item-rows'),count=document.getElementById('item-count'),pager=document.getElementById('item-pagination'),search=document.getElementById('item-search'),modes=document.getElementById('view-modes');
      var mode=(modes.querySelector('.active')||{}).dataset?.view||'hibrida',page=1;
      var backdrop=document.getElementById('detail-backdrop'),close=document.getElementById('detail-close');
      close.onclick=function(){detailRequestId++;backdrop.hidden=true};backdrop.onclick=function(e){if(e.target===backdrop)close.click()};
      document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!backdrop.hidden)close.click()});
      function imageUrl(value){try{var u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:''}catch(e){return ''}}
      var detailRequestId=0;
      async function openDetail(g){
        var requestId=++detailRequestId;
        backdrop.hidden=false;document.getElementById('detail-title').textContent=g.title;
        document.getElementById('detail-account').textContent=g.sources.map(function(s){return s.account+' · '+s.codes.join(', ')}).join(' | ');
        var status=document.getElementById('detail-status'),chart=document.getElementById('detail-chart'),summary=document.getElementById('detail-summary'),tabs=document.getElementById('detail-chart-modes'),tip=document.getElementById('detail-tooltip');
        chart.textContent='';summary.textContent='';tabs.textContent='';tip.hidden=true;
        if(g.level==='campaign'){status.textContent='Série por campanha N/D: o recibo disponível é por anúncio MLB, não por campanha. Nenhum valor de vendas foi atribuído a esta campanha.';return}
        [['Receita',money(g.totalRevenue)],['Pedidos',fmt(g.orders)],['Unidades',fmt(g.units)],['Investimento Ads',money(g.investment)],['TACOS',pct(g.totalRevenue?g.investment/g.totalRevenue:null)],['ROAS',g.investment?(g.adsRevenue/g.investment).toLocaleString('pt-BR',{maximumFractionDigits:2})+'x':'N/D']].forEach(function(pair){var el=document.createElement('span');el.textContent=pair[0]+': '+pair[1];summary.appendChild(el)});
        if(!g.sources.length){status.textContent='Série diária N/D: não há código MLB comprovado para este agrupamento.';return}
        status.textContent='Carregando séries diárias das contas de origem…';
        var period=JSON.parse(document.getElementById('consolidated-period').textContent),from=period.dateFrom,to=period.dateTo;
        var chunks=[];g.sources.forEach(function(source){for(var i=0;i<source.codes.length;i+=50)chunks.push({account_id:source.account_id,codes:source.codes.slice(i,i+50)})});
        try{
          var payloads=new Array(chunks.length),next=0;
          async function worker(){while(next<chunks.length){var index=next++,part=chunks[index],qs=new URLSearchParams({account_id:String(part.account_id),codes:part.codes.join(','),date_from:from,date_to:to}),controller=new AbortController(),timer=setTimeout(function(){controller.abort()},60000);
            try{var response=await fetch('/online/consolidado/item-daily?'+qs,{credentials:'same-origin',signal:controller.signal}),data=await response.json();payloads[index]={...part,http:response.status,data:data}}
            catch(error){payloads[index]={...part,http:0,data:{ok:false,error:error.name==='AbortError'?'timeout':'falha_de_rede_ou_resposta_invalida'}}}
            finally{clearTimeout(timer)}}}
          await Promise.all([worker(),worker()]);
          if(requestId!==detailRequestId)return;
          var failed=payloads.find(function(part){return part.http<200||part.http>=300||part.data.ok!==true});if(failed){status.textContent='Série diária N/D: conta '+failed.account_id+'; '+(failed.http?'HTTP '+failed.http:'sem resposta HTTP')+'; motivo '+(failed.data.error||'resposta indisponível')+'; trace '+(failed.data.trace_id||'sem trace')+'. Nenhum zero foi inventado.';return}
          var first=new Date(from+'T12:00:00Z'),last=new Date(to+'T12:00:00Z'),rows=[];
          for(var day=new Date(first);day<=last;day.setUTCDate(day.getUTCDate()+1))rows.push({date:day.toISOString().slice(0,10),revenue:0,adsRevenue:0,investment:0,units:0,orders:0});
          var salesIssue='',adsIssue='';
          payloads.forEach(function(part){part.codes.forEach(function(code){var source=new Map((part.data.series[code]||[]).map(function(row){return [row.date,row]}));rows.forEach(function(day){var row=source.get(day.date),coverage=part.data.coverage||{};
            if(!coverage.sales||coverage.sales[day.date]!==true){salesIssue=salesIssue||('vendas sem recibo: conta '+part.account_id+', '+code+', '+day.date+'; trace '+part.data.trace_id);return}
            if(row&&row.salesPresent===true){for(var key of ['revenue','orders','units']){if(typeof row[key]!=='number'||!Number.isFinite(row[key])){salesIssue=salesIssue||('valor de vendas inválido: '+code+', '+day.date);return}}day.revenue+=row.revenue;day.orders+=row.orders;day.units+=row.units}
            if(!coverage.ads||coverage.ads[day.date]!==true){adsIssue=adsIssue||('Ads sem recibo: conta '+part.account_id+', '+code+', '+day.date+'; trace '+part.data.trace_id);return}
            if(row&&row.adsPresent===true){for(var key of ['adsRevenue','investment']){if(typeof row[key]!=='number'||!Number.isFinite(row[key])){adsIssue=adsIssue||('valor Ads inválido: '+code+', '+day.date);return}}day.adsRevenue+=row.adsRevenue;day.investment+=row.investment}
          })})});
          function dailySum(key){return rows.reduce(function(sum,row){return sum+row[key]},0)}
          if(salesIssue){status.textContent='Série diária N/D: '+salesIssue;return}
          if(g.totalRevenue==null||Math.abs(dailySum('revenue')-g.totalRevenue)>0.01){status.textContent='Série diária N/D: soma divergente do total do agrupamento ('+money(dailySum('revenue'))+' versus '+money(g.totalRevenue)+').';return}
          if(g.units==null||Math.abs(dailySum('units')-g.units)>0.01||g.orders==null||Math.abs(dailySum('orders')-g.orders)>0.01){status.textContent='Série diária N/D: unidades ou pedidos divergentes do total do agrupamento.';return}
          if(!adsIssue&&(!Number.isFinite(g.adsRevenue)||!Number.isFinite(g.investment)||Math.abs(dailySum('adsRevenue')-g.adsRevenue)>0.01||Math.abs(dailySum('investment')-g.investment)>0.01)){adsIssue='soma diária de Ads divergente do total do agrupamento'}
          var adsComplete=!adsIssue;
          status.textContent=adsComplete?'Séries certificadas das '+g.accountCount+' conta(s) para a janela selecionada.':'Vendas diárias completas; '+adsIssue;
          var metrics=[['revenue','Faturamento'],['adsRevenue','Receita Ads'],['investment','Investimento'],['roas','ROAS'],['tacos','TACOS'],['units','Unidades'],['orders','Pedidos'],['price','Preço médio']];
          function metricValue(row,key){if(['adsRevenue','investment','roas','tacos'].includes(key)&&!adsComplete)return null;if(key==='roas')return row.investment>0?row.adsRevenue/row.investment:null;if(key==='tacos')return row.revenue>0?row.investment/row.revenue:null;if(key==='price')return row.units>0?row.revenue/row.units:null;return row[key]}
          function display(value,key){if(value==null||!Number.isFinite(value))return 'N/D';if(['revenue','adsRevenue','investment','price'].includes(key))return money(value);if(key==='tacos')return pct(value);if(key==='roas')return value.toLocaleString('pt-BR',{maximumFractionDigits:2})+'x';return fmt(value)}
          function drawDetail(key){chart.textContent='';tip.hidden=true;Array.from(tabs.children).forEach(function(button){button.classList.toggle('active',button.dataset.metric===key)});
            var values=rows.map(function(row){return metricValue(row,key)}),valid=values.filter(Number.isFinite);if(valid.length!==rows.length){chart.textContent='N/D — cobertura diária insuficiente para esta métrica.';return}
            var total=valid.reduce(function(a,b){return a+b},0),average=total/rows.length;
            if(key==='roas'){var spend=rows.reduce(function(sum,row){return sum+row.investment},0);average=spend>0?rows.reduce(function(sum,row){return sum+row.adsRevenue},0)/spend:0}
            if(key==='tacos'){var base=rows.reduce(function(sum,row){return sum+row.revenue},0);average=base>0?rows.reduce(function(sum,row){return sum+row.investment},0)/base:0}
            var width=1000,height=300,left=80,right=24,top=43,bottom=48,max=Math.max(.01,...valid,average)*1.12,plotW=width-left-right,plotH=height-top-bottom,ns='http://www.w3.org/2000/svg';
            function element(tag,attributes,parent){var el=document.createElementNS(ns,tag);Object.keys(attributes).forEach(function(name){el.setAttribute(name,attributes[name])});parent.appendChild(el);return el}
            var svg=element('svg',{viewBox:'0 0 '+width+' '+height,role:'img','aria-label':metrics.find(function(metric){return metric[0]===key})[1]+' diário do produto'},chart),x=function(index){return left+(index+.5)*plotW/rows.length},y=function(value){return top+plotH-value/max*plotH};
            for(var tick=0;tick<=4;tick++){var amount=max*tick/4,yy=y(amount);element('line',{x1:left,y1:yy,x2:width-right,y2:yy,class:'chart-grid'},svg);var label=element('text',{x:left-9,y:yy+4,'text-anchor':'end',class:'chart-axis'},svg);label.textContent=display(amount,key)}
            element('line',{x1:left,y1:y(average),x2:width-right,y2:y(average),stroke:'#f59e0b','stroke-width':2,'stroke-dasharray':'7 5'},svg);var mean=element('text',{x:width-right,y:23,'text-anchor':'end',fill:'#b45309','font-size':13,'font-weight':700},svg);mean.textContent='Média do período '+display(average,key);
            var lineOnly=['roas','tacos','price'].includes(key),step=plotW/rows.length,barWidth=Math.min(28,step*.65),points=[];
            rows.forEach(function(row,index){var xx=x(index),value=values[index];if(!lineOnly)element('rect',{x:xx-barWidth/2,y:y(value),width:barWidth,height:Math.max(0,top+plotH-y(value)),rx:Math.min(6,barWidth/3),fill:'#a98de8','fill-opacity':'.65'},svg);var neighbors=values.slice(Math.max(0,index-1),Math.min(values.length,index+2)),smooth=lineOnly?value:neighbors.reduce(function(a,b){return a+b},0)/neighbors.length;points.push(xx+','+y(smooth));if(index%Math.max(1,Math.ceil(rows.length/8))===0||index===rows.length-1){var label=element('text',{x:xx,y:height-14,'text-anchor':'middle',class:'chart-axis'},svg);label.textContent=new Date(row.date+'T12:00:00').toLocaleDateString('pt-BR',{day:'numeric',month:'short'})}});
            element('polyline',{points:points.join(' '),fill:'none',stroke:'#7651d4','stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},svg);
            rows.forEach(function(row,index){var xx=x(index),hit=element('rect',{x:xx-step/2,y:top,width:step,height:plotH,class:'chart-hit'},svg);hit.addEventListener('pointermove',function(){tip.textContent='';var heading=document.createElement('b');heading.textContent=new Date(row.date+'T12:00:00').toLocaleDateString('pt-BR',{day:'numeric',month:'short',year:'numeric'});tip.appendChild(heading);metrics.forEach(function(metric){var line=document.createElement('div'),label=document.createElement('span'),value=document.createElement('strong');label.textContent=metric[1];value.textContent=display(metricValue(row,metric[0]),metric[0]);line.append(label,value);tip.appendChild(line)});tip.style.left=Math.max(105,Math.min(svg.clientWidth-105,xx/width*svg.clientWidth))+'px';tip.style.top='8px';tip.style.transform='translateX(-50%)';tip.hidden=false});hit.addEventListener('pointerleave',function(){tip.hidden=true})})}
          metrics.forEach(function(metric){var button=document.createElement('button');button.type='button';button.dataset.metric=metric[0];button.textContent=metric[1];button.onclick=function(){drawDetail(metric[0])};tabs.appendChild(button)});drawDetail('revenue');
        }catch(e){if(requestId===detailRequestId)status.textContent='Série diária indisponível. Nenhum zero foi inventado.'}
      }
      function fmt(x){return x==null?'N/D':Number(x).toLocaleString('pt-BR',{maximumFractionDigits:0})}
      function money(x){return x==null?'N/D':'R$ '+Number(x).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
      function pct(x){return x==null||!Number.isFinite(x)?'N/D':(100*x).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+'%'}
      function ratio(a,b){return a==null||b==null||b<=0?null:a/b}
      function cell(row,value){var td=document.createElement('td');td.textContent=value;row.appendChild(td)}
      function matches(node,query){return [node.title,node.account,node.code,node.sku,node.key].some(function(value){return String(value||'').toLocaleLowerCase('pt-BR').includes(query)})||node.children.some(function(child){return matches(child,query)})}
      function makePhoto(node,container){var url=imageUrl(node.thumbnailUrl);var photo=document.createElement(url?'img':'span');photo.className='product-photo'+(url?'':' empty');if(url)photo.src=url;else photo.textContent='Sem foto';container.appendChild(photo)}
      function detailButton(node){var button=document.createElement('button');button.type='button';button.className='detail-open';button.textContent='Abrir gráfico';button.onclick=function(event){event.stopPropagation();openDetail(node)};return button}
      function atLevel(nodes,level){var out=[];nodes.forEach(function(node){if(node.level===level)out.push(node);else out.push.apply(out,atLevel(node.children,level))});return out}
      function visibleNodes(){if(mode==='familia')return atLevel(roots,'family');if(mode==='variacao')return atLevel(roots,'mlbu');if(mode==='mlb')return atLevel(roots,'mlb');if(mode==='campanha')return atLevel(roots,'campaign');return roots}
      var expanded=new Set(),period=JSON.parse(document.getElementById('consolidated-period').textContent);
      function metric7d(node,key){var performance=node.performance7d||{},value=performance[key];return performance.date_to===period.dateTo&&value&&value.complete===true&&Number.isFinite(value.current)&&Number.isFinite(value.previous)?value:null}
      function trend(value){if(!value)return 'N/D';var delta=value.current-value.previous,change=value.previous===0?(delta===0?'0%':'sem base'):(delta/value.previous*100).toLocaleString('pt-BR',{maximumFractionDigits:1})+'%';return (delta>0?'▲ ':delta<0?'▼ ':'= ')+change}
      function performanceCell(tr,node){var td=document.createElement('td'),sales=metric7d(node,'sales'),visits=metric7d(node,'visits');
        [['Vendas',sales],['Visitas',visits]].forEach(function(pair){var line=document.createElement('div');line.textContent=pair[0]+': '+(pair[1]?fmt(pair[1].current)+' ('+trend(pair[1])+')':'N/D');td.appendChild(line)});
        var conversion=document.createElement('div');conversion.textContent='Conversão: '+(sales&&visits&&visits.current>0&&visits.previous>0?pct(sales.current/visits.current)+' ('+trend({current:sales.current/visits.current,previous:sales.previous/visits.previous})+')':'N/D');td.appendChild(conversion);tr.appendChild(td)}
      function priceCell(tr,node){var td=document.createElement('td'),current=node.currentPrice!=null?money(node.currentPrice):(node.priceMin!=null&&node.priceMax!=null?money(node.priceMin)+' a '+money(node.priceMax):'N/D');
        [['Atual',current],['Médio',money(node.avgSalePrice)],['Último',money(node.lastSalePrice)]].forEach(function(pair){var line=document.createElement('div');line.textContent=pair[0]+': '+pair[1];td.appendChild(line)});tr.appendChild(td)}
      function appendRow(node,path,depth,fragment){var tr=document.createElement('tr'),td=document.createElement('td'),wrap=document.createElement('div');tr.className='hierarchy-row level-'+node.level;wrap.className='product-name';wrap.style.paddingLeft=(depth*16)+'px';
        if(node.children.length){var toggle=document.createElement('button'),isOpen=expanded.has(path);toggle.type='button';toggle.className='hierarchy-toggle';toggle.textContent=isOpen?'−':'+';toggle.setAttribute('aria-label',(isOpen?'Ocultar':'Mostrar')+' níveis de '+node.title);toggle.setAttribute('aria-expanded',String(isOpen));toggle.onclick=function(){if(expanded.has(path))expanded.delete(path);else expanded.add(path);draw()};wrap.appendChild(toggle)}
        makePhoto(node,wrap);var label=document.createElement('span'),title=document.createElement('b');title.textContent=node.title;label.appendChild(title);var level=document.createElement('small');level.textContent=({global:'Produto entre contas',account:'Conta',family:'Família',mlbu:'Variação/MLBU',mlb:'Anúncio MLB',campaign:'Campanha'})[node.level];label.appendChild(level);wrap.appendChild(label);td.appendChild(wrap);tr.appendChild(td);
        cell(tr,node.level==='global'?node.accountCount+' conta(s)':node.account);cell(tr,node.level==='global'&&node.confidence==='last_sale_reference'?'SKU de referência — associação provisória':node.level==='global'&&node.confidence==='sku_text_unverified'?'SKU declarado — vínculo não comprovado':node.code||node.sku||node.key);
        priceCell(tr,node);cell(tr,node.lastSaleDate||'N/D');cell(tr,money(node.totalRevenue));cell(tr,fmt(node.orders));cell(tr,fmt(node.units));cell(tr,money(node.investment));cell(tr,money(node.adsRevenue));var roas=ratio(node.adsRevenue,node.investment);cell(tr,roas==null?'N/D':roas.toLocaleString('pt-BR',{maximumFractionDigits:2})+'x');cell(tr,pct(ratio(node.investment,node.totalRevenue)));cell(tr,pct(ratio(node.investment,node.adsRevenue)));cell(tr,node.visitsKnown?fmt(node.visits):'N/D');performanceCell(tr,node);
        var detail=document.createElement('td');detail.appendChild(detailButton(node));tr.appendChild(detail);fragment.appendChild(tr);
        if(expanded.has(path))node.children.forEach(function(child,index){appendRow(child,path+'/'+index+':'+child.key,depth+1,fragment)})}
      function draw(){var query=search.value.trim().toLocaleLowerCase('pt-BR'),all=visibleNodes().filter(function(node){return !query||matches(node,query)}),pages=Math.max(1,Math.ceil(all.length/100));page=Math.max(1,Math.min(page,pages));body.textContent='';
        var fragment=document.createDocumentFragment();all.slice((page-1)*100,page*100).forEach(function(node,index){appendRow(node,index+':'+node.key,0,fragment)});body.appendChild(fragment);
        count.textContent='Página '+page+' de '+pages+' · '+all.length+' agrupamentos em '+mode+', ordenados por receita.';pager.textContent='';if(page>1){var prev=document.createElement('button');prev.type='button';prev.textContent='Anterior';prev.onclick=function(){page--;draw()};pager.appendChild(prev)}if(page<pages){var next=document.createElement('button');next.type='button';next.textContent='Próxima';next.onclick=function(){page++;draw()};pager.appendChild(next)}
        Array.from(modes.querySelectorAll('a')).forEach(function(a){a.classList.toggle('active',a.dataset.view===mode)})}
      modes.addEventListener('click',function(e){var a=e.target.closest('a[data-view]');if(!a)return;e.preventDefault();mode=a.dataset.view;page=1;draw()});search.addEventListener('input',function(){page=1;draw()});draw();
    })();</script>'''
    comparison_script = ''
    if overall_complete:
        comparison_data = json.dumps({"accounts": sorted(selected_ids), "period": period,
                                      "current": result["sums"]}, separators=(",", ":")).replace("<", "\\u003c")
        comparison_script = '''<script type="application/json" id="comparison-request">{}</script><script>
        (async function(){{var source=document.getElementById('comparison-request');if(!source)return;
          var config=JSON.parse(source.textContent), previous=new Array(config.accounts.length), next=0;
          async function loadPrevious(id){{
            var qs=new URLSearchParams({{account_id:String(id),period:config.period.mode||'30d',date_from:config.period.dateFrom,date_to:config.period.dateTo}});
            for(var attempt=0;attempt<2;attempt++){{
              var controller=new AbortController(),timer=setTimeout(function(){{controller.abort()}},60000);
              try{{var response=await fetch('/online/consolidado/comparison?'+qs,{{credentials:'same-origin',signal:controller.signal}});
                var data=await response.json();
                if(response.ok&&data.ok&&data.period&&data.period.dateFrom===config.period.comparePeriod.dateFrom&&data.period.dateTo===config.period.comparePeriod.dateTo)return data.summary;
                if(response.status===401||response.status===403||response.status===400||response.status===409)return null;
              }}catch(error){{}}
              finally{{clearTimeout(timer)}}
            }}
            return null;
          }}
          async function loadNext(){{while(next<config.accounts.length){{var index=next++;previous[index]=await loadPrevious(config.accounts[index])}}}}
          await Promise.all([loadNext(),loadNext()]);
          if(previous.some(function(row){{return !row}}))return;
          function total(key){{return previous.every(function(row){{return typeof row[key]==='number'&&Number.isFinite(row[key])}})
            ?previous.reduce(function(sum,row){{return sum+row[key]}},0):null}}
          var old={{revenue:total('revenue'),units:total('units'),orders:total('orders'),visits:total('visits'),
            cancelledOrders:total('cancelledOrders'),
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
    return _layout("Visão consolidada", body + warning + cards + reconciliation + chart + table + script + comparison_script, css)
