import html
import json
import pathlib
import re
import zipfile
import copy
from datetime import datetime
import xml.etree.ElementTree as ET


BASE_DIR = pathlib.Path.cwd()
SALES_FILE = BASE_DIR / "vendas.xlsx"
ADS_FILE = BASE_DIR / "publicidade.xlsx"
LOGO_FILE = pathlib.Path(__file__).resolve().parent / "assets" / "logo-un-clic.png"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def col_to_num(cell_ref):
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return 0
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - 64
    return number


def sheet_paths(zip_file):
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall(f"{PKG}Relationship")}
    paths = {}
    for sheet in workbook.find(f"{NS}sheets").findall(f"{NS}sheet"):
        rid = sheet.attrib.get(f"{REL}id")
        target = relmap.get(rid, "")
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        paths[sheet.attrib["name"]] = target
    return paths


def shared_strings(zip_file):
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    values = []
    with zip_file.open("xl/sharedStrings.xml") as stream:
        for event, elem in ET.iterparse(stream, events=("end",)):
            if elem.tag == f"{NS}si":
                values.append("".join((text.text or "") for text in elem.iter(f"{NS}t")))
                elem.clear()
    return values


def find_sheet_name(path, preferred, contains=None):
    with zipfile.ZipFile(path) as zip_file:
        names = list(sheet_paths(zip_file).keys())
    if preferred in names:
        return preferred
    if contains:
        for name in names:
            lower = name.lower()
            if all(part.lower() in lower for part in contains):
                return name
    raise ValueError(f"Aba nao encontrada. Esperado: {preferred}. Abas disponiveis: {', '.join(names)}")


def has_sheet(path, sheet_name):
    with zipfile.ZipFile(path) as zip_file:
        return sheet_name in sheet_paths(zip_file)


def read_sheet(path, sheet_name):
    with zipfile.ZipFile(path) as zip_file:
        paths = sheet_paths(zip_file)
        if sheet_name not in paths:
            sheet_name = find_sheet_name(path, sheet_name)
        shared = shared_strings(zip_file)
        rows = []
        with zip_file.open(paths[sheet_name]) as stream:
            for event, elem in ET.iterparse(stream, events=("end",)):
                if elem.tag == f"{NS}row":
                    row = {}
                    for cell in elem.findall(f"{NS}c"):
                        col = col_to_num(cell.attrib.get("r", ""))
                        typ = cell.attrib.get("t")
                        value = ""
                        if typ == "inlineStr":
                            value = "".join((text.text or "") for text in cell.iter(f"{NS}t"))
                        else:
                            node = cell.find(f"{NS}v")
                            if node is not None and node.text is not None:
                                value = node.text
                                if typ == "s":
                                    try:
                                        value = shared[int(value)]
                                    except Exception:
                                        pass
                        row[col] = value
                    rows.append((int(elem.attrib.get("r", "0") or 0), row))
                    elem.clear()
        return rows


def number(value):
    if value in (None, "", "-", " "):
        return 0.0
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return 0.0


def text(value):
    return "" if value is None else str(value).strip()


def parse_ml_date(value):
    raw = text(value).lower()
    if not raw:
        return 0
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "março": 3,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    match = re.search(r"(\d{1,2}) de ([a-zç]+) de (\d{4})(?:\s+(\d{1,2}):(\d{2}))?", raw)
    if not match:
        return 0
    day = int(match.group(1))
    month = months.get(match.group(2), 0)
    year = int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    return year * 100000000 + month * 1000000 + day * 10000 + hour * 100 + minute


def parse_ml_datetime(value):
    raw = text(value).lower()
    if not raw:
        return None
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marÃ§o": 3,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    match = re.search(r"(\d{1,2}) de ([a-zÃ§]+) de (\d{4})(?:\s+(\d{1,2}):(\d{2}))?", raw)
    if not match:
        return None
    month = months.get(match.group(2), 0)
    if not month:
        return None
    return datetime(
        int(match.group(3)),
        month,
        int(match.group(1)),
        int(match.group(4) or 0),
        int(match.group(5) or 0),
    )


def is_active_status(value):
    raw = text(value).lower()
    if not raw:
        return False
    return raw.startswith("ativo") or raw.startswith("ativa")


def logo_data_uri():
    if not LOGO_FILE.exists():
        return ""
    import base64
    return "data:image/png;base64," + base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")


def decision(item):
    investment = item["investment"]
    total_revenue = item["totalRevenue"]
    tacos = item["tacos"]
    units = item["units"]
    campaign = item["campaign"].lower()
    ads_revenue = item.get("adsRevenue", 0)
    cvr = item.get("cvr", 0)

    if investment > 0 and total_revenue <= 0:
        return "Investigar urgente", "Investiu, mas nao apareceu venda total no relatorio."
    if investment > 0 and ads_revenue <= 0:
        return "Pausar ou revisar", "Tem gasto em ADS sem venda atribuida."
    if investment == 0 and units > 0:
        return "Oportunidade", "Vende sem ADS; avaliar campanha se houver estoque e margem."
    if investment > 0 and tacos > 0.03:
        return "Otimizar", "TACOS acima da meta de 3%."
    if investment > 0 and tacos <= 0.03 and ads_revenue > 0:
        if tacos <= 0.02 and cvr >= 0.06:
            return "Manter assim", "Saudavel; priorizar itens com maior necessidade e voltar se metricas mudarem."
        return "Manter", "Dentro da meta; avaliar margem e estoque antes de subir verba."
    if "inativo" in campaign and units > 0:
        return "Oportunidade", "Produto vende, mas esta inativo em campanha."
    return "Investigar", "Dados insuficientes para decisao automatica."


def ctr_class(ctr_percent):
    if ctr_percent < 2:
        return "Baixo"
    if ctr_percent < 3:
        return "Regular"
    if ctr_percent < 4:
        return "Bom"
    return "Otimo"


def cvr_class(cvr_percent):
    if cvr_percent <= 0:
        return "Sem conversao"
    if cvr_percent < 3:
        return "Baixa"
    if cvr_percent < 6:
        return "Regular"
    if cvr_percent < 10:
        return "Boa"
    if cvr_percent < 15:
        return "Muito boa"
    return "Excelente"


def apply_alerts(item):
    alerts = []
    recommendations = []
    investment = item.get("investment", 0) or 0
    total_revenue = item.get("totalRevenue", 0) or 0
    ads_revenue = item.get("adsRevenue", 0) or 0
    units = item.get("units", 0) or 0
    impressions = item.get("impressions", 0) or 0
    clicks = item.get("clicks", 0) or 0
    tacos = item.get("tacos", 0) or 0
    ctr = item.get("ctr", 0) or 0
    cvr = item.get("cvr", 0) or 0
    cpc = item.get("cpc", 0) or 0
    max_cpc = item.get("maxCpc", 0) or 0

    ctr_label = ctr_class(ctr * 100)
    cvr_label = cvr_class(cvr * 100)
    item["ctrClass"] = ctr_label
    item["cvrClass"] = cvr_label

    if investment > 0 and total_revenue <= 0:
        alerts.append("Investimento sem venda total")
        recommendations.append("Investigar periodo, cruzamento MLB/SKU e campanha.")
    if investment > 0 and ads_revenue <= 0:
        alerts.append("Investimento sem venda ADS")
        recommendations.append("Revisar campanha/anuncio antes de manter verba.")
    if investment > 0 and tacos > 0.03:
        alerts.append("TACOS acima de 3%")
        recommendations.append("Otimizar verba, segmentacao, CPC ou oferta.")
    if clicks >= 50 and cpc > 0 and max_cpc > 0 and cpc > max_cpc * 1.5:
        if 0 < tacos <= 0.03 and cvr_label in ("Boa", "Muito boa", "Excelente"):
            alerts.append("CPC acima do calculado")
            recommendations.append("CPC ficou acima do calculo, mas TACOS/CVR estao saudaveis; validar formula antes de agir.")
        else:
            alerts.append("CPC acima do sustentavel")
            recommendations.append("Verificar CPC, termos e segmentacao; nao decidir por CPC isolado.")
    if clicks >= 20 and investment > 0 and ads_revenue <= 0:
        alerts.append("Clique pago sem venda ADS")
        recommendations.append("Termo/anuncio provavelmente ruim; isolar, reduzir ou pausar ate validar.")
    if ctr_label in ("Bom", "Otimo") and cvr_label in ("Sem conversao", "Baixa") and clicks >= 50:
        alerts.append("CTR bom e CVR baixo")
        recommendations.append("Anuncio atrai, mas a pagina/oferta nao convence.")
    if ctr_label == "Baixo" and cvr_label in ("Boa", "Muito boa", "Excelente") and impressions >= 1000:
        alerts.append("CTR baixo e CVR alto")
        recommendations.append("Poucos clicam, mas quem clica compra; se for prioridade, pesquisar palavras e melhorar atratividade sem mexer agressivamente.")
    elif impressions >= 1000 and ctr_label == "Baixo":
        alerts.append("CTR baixo com muitas impressoes")
        recommendations.append("Revisar imagem, titulo, preco, frete e relevancia.")
    if clicks >= 50 and cvr_label in ("Sem conversao", "Baixa"):
        alerts.append("CVR baixo com volume de cliques")
        recommendations.append("Revisar preco, prazo, reputacao, pagina, variacoes e oferta.")
    if ctr_label in ("Bom", "Otimo") and cvr_label in ("Boa", "Muito boa", "Excelente") and investment > 0 and 0 < tacos <= 0.03:
        alerts.append("Candidato a escala")
        recommendations.append("Validar margem, estoque e aumentar verba gradualmente.")
    if cvr_label in ("Muito boa", "Excelente") and tacos > 0.03:
        alerts.append("CVR alto com TACOS ruim")
        recommendations.append("Produto vende, mas clique/campanha esta caro ou margem nao cobre.")
    if cvr_label in ("Sem conversao", "Baixa") and investment > 0 and ads_revenue > 0 and 0 < tacos <= 0.03:
        alerts.append("CVR baixo com TACOS bom")
        recommendations.append("Nao pausar automaticamente; pode ter baixo volume ou ticket alto.")
    if investment == 0 and units > 0:
        alerts.append("Venda sem ADS")
        recommendations.append("Avaliar campanha se houver margem e estoque.")
    if item.get("priceAboveAverage"):
        alerts.append("Preco acima da media")
        recommendations.append("Ultimo preco ficou mais de 5% acima da media; verificar promocao/preco.")
    if item.get("salesPaceAlert"):
        alerts.append("Tempo sem venda acima da media")
        recommendations.append("Produto esta ha mais tempo sem vender do que o ritmo medio; verificar preco, promocao ou estoque.")
    if item.get("possibleCatalog"):
        alerts.append("Possivel catalogo/sincronizado")
        recommendations.append("SKU aparece ligado a mais de um MLB; validar catalogo, buy box ou anuncios sincronizados no Mercado Livre.")

    if not alerts:
        if investment > 0 and ads_revenue > 0 and 0 < tacos <= 0.03:
            alerts.append("Dentro da meta")
            recommendations.append("Manter e acompanhar margem/estoque.")
        else:
            alerts.append("Sem alerta critico")
            recommendations.append("Monitorar.")

    item["alerts"] = alerts
    item["alertText"] = " | ".join(alerts)
    item["recommendation"] = " | ".join(dict.fromkeys(recommendations))


def mark_possible_catalog(items):
    sku_codes = {}
    for item in items:
        sku = item.get("sku")
        code = item.get("code")
        if sku and code:
            sku_codes.setdefault(sku, set()).add(code)
    possible_skus = {sku for sku, codes in sku_codes.items() if len(codes) > 1}
    for item in items:
        item["possibleCatalog"] = bool(item.get("sku") in possible_skus)


def apply_sku_campaign_context(items):
    sku_active_campaigns = {}
    for item in items:
        sku = item.get("sku")
        if not sku or item.get("campaignStatus") != "Ativa":
            continue
        campaigns = item.get("adsCampaigns") or item.get("campaign") or ""
        for campaign in [part.strip() for part in campaigns.split(",") if part.strip()]:
            sku_active_campaigns.setdefault(sku, set()).add(campaign)

    for item in items:
        sku = item.get("sku")
        if not sku or item.get("campaignStatus") == "Ativa":
            continue
        campaigns = sorted(sku_active_campaigns.get(sku, set()))
        if campaigns:
            item["relatedActiveCampaigns"] = ", ".join(campaigns)
            item["campaign"] = item["relatedActiveCampaigns"]
            item["adsCampaigns"] = item["relatedActiveCampaigns"]
            item["campaignStatus"] = "Ativa por SKU"


def abc_label(cumulative_share):
    if cumulative_share <= 0.80:
        return "A"
    if cumulative_share <= 0.95:
        return "B"
    return "C"


def apply_abc(items, field_name, target_name):
    ranked = sorted(items, key=lambda item: item.get(field_name, 0) or 0, reverse=True)
    total = sum(item.get(field_name, 0) or 0 for item in ranked)
    cumulative = 0
    for item in ranked:
        cumulative += item.get(field_name, 0) or 0
        item[target_name] = abc_label(cumulative / total) if total else "C"


def read_treated_sales(sales_file):
    sales_rows = read_sheet(sales_file, "Planilha2")
    sales = {}
    for row_number, row in sales_rows:
        if row_number < 2:
            continue
        code = text(row.get(1))
        if not code or not code.startswith("MLB"):
            continue
        item = {
            "sku": "",
            "code": code,
            "title": text(row.get(2)),
            "lastSaleDate": "",
            "lastSaleSort": 0,
            "lastSaleDay": 0,
            "firstSaleDay": 0,
            "lastPrice": 0,
            "avgSalePrice": 0,
            "avgDailyUnits": 0,
            "daysSinceLastSale": 0,
            "avgGapDays": 0,
            "priceAboveAverage": False,
            "salesPaceAlert": False,
            "possibleCatalog": False,
            "units": number(row.get(3)),
            "unitsShare": number(row.get(4)),
            "productRevenue": number(row.get(5)),
            "revenueShare": number(row.get(6)),
            "indirectRevenue": number(row.get(7)),
            "totalRevenue": number(row.get(8)),
            "investment": number(row.get(9)),
            "tacos": number(row.get(10)),
            "roas": number(row.get(11)),
            "campaign": text(row.get(12)) or "Inativo",
        }
        sales[code] = item
    return sales


def read_raw_sales(sales_file):
    sales_rows = read_sheet(sales_file, "Vendas BR")
    header = {}
    for row_number, row in sales_rows:
        if row_number == 6:
            for col, value in row.items():
                label = text(value)
                if label and label not in header:
                    header[label] = col
            break

    code_col = header.get("# de anúncio", 23)
    sku_col = header.get("SKU", 22)
    date_col = header.get("Data da venda", 2)
    units_col = header.get("Unidades", 7)
    revenue_col = header.get("Receita por produtos (BRL)", 8)
    title_col = header.get("Título do anúncio", 26)
    unit_price_col = header.get("Preço unitário de venda do anúncio (BRL)", 28)

    sales = {}
    report_last_day = 0
    for row_number, row in sales_rows:
        if row_number < 7:
            continue
        code = text(row.get(code_col))
        if not code or not code.startswith("MLB"):
            continue
        units = number(row.get(units_col))
        unit_price = number(row.get(unit_price_col))
        product_revenue = number(row.get(revenue_col))
        sale_date = text(row.get(date_col))
        sale_sort = parse_ml_date(sale_date)
        sale_dt = parse_ml_datetime(sale_date)
        sale_day = sale_dt.toordinal() if sale_dt else 0
        if sale_day:
            report_last_day = max(report_last_day, sale_day)
        if product_revenue == 0 and unit_price and units:
            product_revenue = unit_price * units
        if units == 0 and product_revenue:
            units = 1
        item = sales.setdefault(code, {
            "sku": text(row.get(sku_col)),
            "code": code,
            "title": text(row.get(title_col)),
            "lastSaleDate": "",
            "lastSaleSort": 0,
            "lastSaleDay": 0,
            "firstSaleDay": 0,
            "lastPrice": 0,
            "avgSalePrice": 0,
            "priceTotal": 0,
            "priceCount": 0,
            "units": 0,
            "unitsShare": 0,
            "productRevenue": 0,
            "revenueShare": 0,
            "indirectRevenue": 0,
            "totalRevenue": 0,
            "investment": 0,
            "tacos": 0,
            "roas": 0,
            "campaign": "Inativo",
        })
        if not item["title"] and text(row.get(title_col)):
            item["title"] = text(row.get(title_col))
        if not item["sku"] and text(row.get(sku_col)):
            item["sku"] = text(row.get(sku_col))
        if unit_price and sale_sort >= item.get("lastSaleSort", 0):
            item["lastSaleDate"] = sale_date
            item["lastSaleSort"] = sale_sort
            item["lastSaleDay"] = sale_day
            item["lastPrice"] = unit_price
        if sale_day:
            item["firstSaleDay"] = sale_day if not item.get("firstSaleDay") else min(item["firstSaleDay"], sale_day)
        if unit_price:
            item["priceTotal"] += unit_price
            item["priceCount"] += 1
        item["units"] += units
        item["productRevenue"] += product_revenue

    total_units = sum(item["units"] for item in sales.values())
    total_revenue = sum(item["productRevenue"] for item in sales.values())
    for item in sales.values():
        item["unitsShare"] = item["units"] / total_units if total_units else 0
        item["revenueShare"] = item["productRevenue"] / total_revenue if total_revenue else 0
        item["totalRevenue"] = item["productRevenue"]
        item["avgSalePrice"] = item["priceTotal"] / item["priceCount"] if item["priceCount"] else 0
        item["priceAboveAverage"] = bool(item["lastPrice"] and item["avgSalePrice"] and item["lastPrice"] > item["avgSalePrice"] * 1.05)
        active_days = (report_last_day - item["firstSaleDay"] + 1) if report_last_day and item.get("firstSaleDay") else 0
        avg_daily_units = item["units"] / active_days if active_days else 0
        days_since_sale = (report_last_day - item["lastSaleDay"]) if report_last_day and item.get("lastSaleDay") else 0
        avg_gap_days = active_days / item["units"] if active_days and item["units"] else 0
        item["avgDailyUnits"] = avg_daily_units
        item["daysSinceLastSale"] = days_since_sale
        item["avgGapDays"] = avg_gap_days
        item["salesPaceAlert"] = bool(avg_gap_days and days_since_sale >= 2 and days_since_sale > avg_gap_days * 1.5)
    return sales


def detect_client_name(sales_file):
    rows = read_sheet(sales_file, "Vendas BR") if has_sheet(sales_file, "Vendas BR") else []
    header = {}
    for row_number, row in rows:
        if row_number == 6:
            for col, value in row.items():
                label = text(value)
                if label and label not in header:
                    header[label] = col
            break
    store_col = header.get("Loja oficial")
    if store_col:
        counts = {}
        for row_number, row in rows:
            if row_number < 7:
                continue
            value = text(row.get(store_col))
            if value:
                counts[value] = counts.get(value, 0) + 1
        if counts:
            candidate, _ = max(counts.items(), key=lambda item: item[1])
            return candidate
    return ""


def aggregate_by_sku(items):
    grouped = {}
    for item in items:
        sku = item.get("sku") or "(sem SKU)"
        target = grouped.setdefault(sku, {
            "sku": sku,
            "code": "",
            "codes": set(),
            "title": "",
            "campaign": "",
            "campaigns": set(),
            "lastSaleDate": "",
            "lastSaleSort": 0,
            "lastSaleDay": 0,
            "firstSaleDay": 0,
            "lastPrice": 0,
            "priceMin": 0,
            "priceMax": 0,
            "priceCount": 0,
            "avgSalePrice": 0,
            "priceTotal": 0,
            "avgDailyUnits": 0,
            "daysSinceLastSale": 0,
            "avgGapDays": 0,
            "priceAboveAverage": False,
            "salesPaceAlert": False,
            "possibleCatalog": False,
            "units": 0,
            "productRevenue": 0,
            "totalRevenue": 0,
            "adsRevenue": 0,
            "investment": 0,
            "impressions": 0,
            "clicks": 0,
            "adsSales": 0,
            "tacos": 0,
            "roas": 0,
            "ctr": 0,
            "cvr": 0,
            "cpc": 0,
            "avgAdsOrder": 0,
            "maxCpc": 0,
            "cvrClass": "Sem conversao",
            "action": "",
            "reason": "",
        })
        if item.get("code"):
            target["codes"].add(item["code"])
        if item.get("campaign") and item["campaign"] != "Inativo":
            target["campaigns"].add(item["campaign"])
        if item.get("adsCampaigns") and item["adsCampaigns"] != item.get("campaign"):
            target["campaigns"].add(item["adsCampaigns"])
        if not target["title"] and item.get("title"):
            target["title"] = item["title"]
        if item.get("lastPrice"):
            price = item.get("lastPrice", 0) or 0
            target["priceMin"] = price if not target["priceMin"] else min(target["priceMin"], price)
            target["priceMax"] = max(target["priceMax"], price)
            target["priceCount"] += 1
            target["priceTotal"] += item.get("avgSalePrice", price) or price
            if item.get("lastSaleSort", 0) >= target.get("lastSaleSort", 0):
                target["lastSaleDate"] = item.get("lastSaleDate", "")
                target["lastSaleSort"] = item.get("lastSaleSort", 0)
                target["lastSaleDay"] = item.get("lastSaleDay", 0)
                target["lastPrice"] = price
        if item.get("firstSaleDay"):
            target["firstSaleDay"] = item["firstSaleDay"] if not target["firstSaleDay"] else min(target["firstSaleDay"], item["firstSaleDay"])
        target["daysSinceLastSale"] = max(target["daysSinceLastSale"], item.get("daysSinceLastSale", 0) or 0)
        target["avgDailyUnits"] += item.get("avgDailyUnits", 0) or 0
        target["priceAboveAverage"] = target["priceAboveAverage"] or item.get("priceAboveAverage", False)
        target["salesPaceAlert"] = target["salesPaceAlert"] or item.get("salesPaceAlert", False)
        target["possibleCatalog"] = target["possibleCatalog"] or item.get("possibleCatalog", False)
        target["units"] += item.get("units", 0) or 0
        target["productRevenue"] += item.get("productRevenue", 0) or 0
        target["totalRevenue"] += item.get("totalRevenue", 0) or 0
        target["adsRevenue"] += item.get("adsRevenue", 0) or 0
        target["investment"] += item.get("investment", 0) or 0
        target["impressions"] += item.get("impressions", 0) or 0
        target["clicks"] += item.get("clicks", 0) or 0
        target["adsSales"] += item.get("adsSales", 0) or 0

    result = []
    for item in grouped.values():
        codes = sorted(item.pop("codes"))
        campaigns = sorted(item.pop("campaigns"))
        item["allCodes"] = ", ".join(codes)
        item["possibleCatalog"] = item.get("possibleCatalog", False) or len(codes) > 1
        item["allCampaigns"] = ", ".join(campaigns)
        item["code"] = ", ".join(codes[:4]) + ("..." if len(codes) > 4 else "")
        item["adCount"] = len(codes)
        item["campaign"] = ", ".join(campaigns[:3]) + ("..." if len(campaigns) > 3 else "")
        item["tacos"] = item["investment"] / item["totalRevenue"] if item["totalRevenue"] else 0
        item["roas"] = item["adsRevenue"] / item["investment"] if item["investment"] else 0
        item["ctr"] = item["clicks"] / item["impressions"] if item["impressions"] else 0
        item["cvr"] = item["adsSales"] / item["clicks"] if item["clicks"] else 0
        item["cpc"] = item["investment"] / item["clicks"] if item["clicks"] else 0
        item["avgAdsOrder"] = item["adsRevenue"] / item["adsSales"] if item["adsSales"] else (item["totalRevenue"] / item["units"] if item["units"] else 0)
        item["maxCpc"] = item["avgAdsOrder"] * 0.03 * item["cvr"] if item["avgAdsOrder"] and item["cvr"] else 0
        item["avgSalePrice"] = item["priceTotal"] / item["priceCount"] if item["priceCount"] else 0
        item["cvrClass"] = cvr_class(item["cvr"] * 100)
        apply_alerts(item)
        action, reason = decision(item)
        item["action"] = action
        item["reason"] = reason
        result.append(item)
    return result


def build_data(sales_file=SALES_FILE, ads_file=ADS_FILE):
    ads_sheet = find_sheet_name(ads_file, "Relatório Anúncios patrocinados", contains=("relat", "patrocin"))
    client_name = detect_client_name(sales_file)
    if has_sheet(sales_file, "Planilha2"):
        sales = read_treated_sales(sales_file)
        sales_source = "tratada"
    else:
        find_sheet_name(sales_file, "Vendas BR")
        sales = read_raw_sales(sales_file)
        sales_source = "virgem"

    ads_rows = read_sheet(ads_file, ads_sheet)
    ads = {}
    for row_number, row in ads_rows:
        if row_number < 3:
            continue
        code = text(row.get(5))
        if not code or not code.startswith("MLB"):
            continue
        target = ads.setdefault(code, {
            "code": code,
            "title": text(row.get(4)),
            "campaigns": set(),
            "activeCampaigns": set(),
            "status": set(),
            "impressions": 0,
            "clicks": 0,
            "adsRevenue": 0,
            "investment": 0,
            "adsSales": 0,
        })
        campaign_name = text(row.get(3))
        status_name = text(row.get(6))
        if campaign_name:
            target["campaigns"].add(campaign_name)
            if is_active_status(status_name):
                target["activeCampaigns"].add(campaign_name)
        if status_name:
            target["status"].add(status_name)
        target["impressions"] += number(row.get(7))
        target["clicks"] += number(row.get(8))
        target["adsRevenue"] += number(row.get(12))
        target["investment"] += number(row.get(13))
        target["adsSales"] += number(row.get(18))

    items = []
    for code, item in sales.items():
        ad = ads.get(code, {})
        item = dict(item)
        item["adsRevenue"] = ad.get("adsRevenue", item["indirectRevenue"])
        item["adsInvestmentRaw"] = ad.get("investment", item["investment"])
        item["indirectRevenue"] = ad.get("adsRevenue", item["indirectRevenue"])
        # Receita total para TACOS deve seguir a venda bruta/receita do relatorio de vendas.
        # A receita atribuida pelo ADS fica separada para ROAS, evitando dupla contagem.
        item["totalRevenue"] = item["productRevenue"]
        item["investment"] = ad.get("investment", item["investment"])
        item["tacos"] = item["investment"] / item["totalRevenue"] if item["totalRevenue"] else 0
        item["roas"] = item["adsRevenue"] / item["investment"] if item["investment"] else 0
        item["impressions"] = ad.get("impressions", 0)
        item["clicks"] = ad.get("clicks", 0)
        item["adsSales"] = ad.get("adsSales", 0)
        item["ctr"] = item["clicks"] / item["impressions"] if item["impressions"] else 0
        item["cvr"] = item["adsSales"] / item["clicks"] if item["clicks"] else 0
        item["cpc"] = item["investment"] / item["clicks"] if item["clicks"] else 0
        item["avgAdsOrder"] = item["adsRevenue"] / item["adsSales"] if item["adsSales"] else (item["totalRevenue"] / item["units"] if item["units"] else 0)
        item["maxCpc"] = item["avgAdsOrder"] * 0.03 * item["cvr"] if item["avgAdsOrder"] and item["cvr"] else 0
        item["cvrClass"] = cvr_class(item["cvr"] * 100)
        active_campaigns = sorted(ad.get("activeCampaigns", []))
        all_campaigns = sorted(ad.get("campaigns", []))
        item["adsCampaigns"] = ", ".join(active_campaigns or all_campaigns) or item["campaign"]
        if active_campaigns:
            item["campaign"] = item["adsCampaigns"]
            item["campaignStatus"] = "Ativa"
        elif all_campaigns:
            item["campaign"] = item["adsCampaigns"]
            item["campaignStatus"] = "Sem campanha ativa"
        else:
            item["campaignStatus"] = "Inativo"
        apply_alerts(item)
        action, reason = decision(item)
        item["action"] = action
        item["reason"] = reason
        items.append(item)

    sales_codes = set(sales)
    ads_only = []
    for code, ad in ads.items():
        if ad["investment"] > 0 and code not in sales_codes:
            ads_only.append({
                "sku": "",
                "code": code,
                "title": ad["title"],
                "lastSaleDate": "",
                "lastSaleSort": 0,
                "lastPrice": 0,
                "units": 0,
                "productRevenue": 0,
                "indirectRevenue": 0,
                "totalRevenue": 0,
                "investment": ad["investment"],
                "tacos": 0,
                "roas": 0,
                "campaign": ", ".join(sorted(ad["campaigns"])),
                "campaignStatus": "Ativa" if ad.get("activeCampaigns") else "Sem campanha ativa",
                "adsRevenue": ad["adsRevenue"],
                "impressions": ad["impressions"],
                "clicks": ad["clicks"],
                "adsSales": ad["adsSales"],
                "ctr": ad["clicks"] / ad["impressions"] if ad["impressions"] else 0,
                "cvr": ad["adsSales"] / ad["clicks"] if ad["clicks"] else 0,
                "cpc": ad["investment"] / ad["clicks"] if ad["clicks"] else 0,
                "avgAdsOrder": ad["adsRevenue"] / ad["adsSales"] if ad["adsSales"] else 0,
                "maxCpc": (ad["adsRevenue"] / ad["adsSales"] * 0.03 * (ad["adsSales"] / ad["clicks"])) if ad["adsSales"] and ad["clicks"] else 0,
                "cvrClass": cvr_class((ad["adsSales"] / ad["clicks"] * 100) if ad["clicks"] else 0),
                "possibleCatalog": False,
                "action": "Investigar urgente",
                "reason": "Investiu em ADS, mas nao apareceu no consolidado de vendas.",
            })
            apply_alerts(ads_only[-1])

    all_decision_items = items + ads_only
    mark_possible_catalog(all_decision_items)
    apply_sku_campaign_context(all_decision_items)
    for item in all_decision_items:
        apply_alerts(item)
        action, reason = decision(item)
        item["action"] = action
        item["reason"] = reason
    sku_ads = aggregate_by_sku(all_decision_items)
    apply_abc(all_decision_items, "totalRevenue", "abcCode")
    apply_abc(sku_ads, "totalRevenue", "abcSku")
    sku_abc = {item["sku"]: item["abcSku"] for item in sku_ads}
    for item in all_decision_items:
        item["abcSku"] = sku_abc.get(item.get("sku") or "(sem SKU)", "C")
    finalizados_sem_sku = [item for item in all_decision_items if not item.get("sku")]
    decision_items = [item for item in all_decision_items if item.get("sku")]
    total_revenue = sum(item["totalRevenue"] for item in items)
    total_investment = sum(item["investment"] for item in items)
    total_ads_revenue = sum(item.get("adsRevenue", 0) for item in items)
    total_clicks = sum(item.get("clicks", 0) for item in all_decision_items)
    total_ads_sales = sum(item.get("adsSales", 0) for item in all_decision_items)
    kpis = {
        "clientName": client_name,
        "salesSource": sales_source,
        "products": len(items),
        "units": sum(item["units"] for item in items),
        "revenue": total_revenue,
        "adsRevenue": total_ads_revenue,
        "investment": total_investment,
        "investmentNoAdsSales": sum(item["investment"] for item in all_decision_items if item["investment"] > 0 and item.get("adsRevenue", 0) <= 0),
        "cvr": total_ads_sales / total_clicks if total_clicks else 0,
        "tacos": total_investment / total_revenue if total_revenue else 0,
        "roas": total_ads_revenue / total_investment if total_investment else 0,
        "adsNoSales": len([item for item in all_decision_items if item["investment"] > 0 and item.get("adsRevenue", 0) <= 0]),
        "adsOnlyNoTotalSales": len(ads_only),
        "tacosHigh": len([item for item in items if item["investment"] > 0 and item["tacos"] > 0.03]),
        "salesNoAds": len([item for item in items if item["units"] > 0 and item["investment"] == 0]),
    }
    return {
        "kpis": kpis,
        "items": sorted(all_decision_items, key=lambda item: (
            0 if not item.get("sku") else
            1 if item["action"] == "Investigar urgente" else
            2 if item["action"] == "Pausar ou revisar" else
            3 if item["action"] == "Otimizar" else
            4 if item["action"] == "Oportunidade" else 5,
            -item["investment"],
            -item["totalRevenue"],
        )),
        "decisionItems": sorted(decision_items, key=lambda item: (
            0 if item["action"] == "Investigar urgente" else
            1 if item["action"] == "Pausar ou revisar" else
            2 if item["action"] == "Otimizar" else
            3 if item["action"] == "Oportunidade" else 4,
            -item["investment"],
            -item["totalRevenue"],
        )),
        "adsNoSales": sorted(
            [item for item in all_decision_items if item["investment"] > 0 and item.get("adsRevenue", 0) <= 0],
            key=lambda item: -item["investment"],
        ),
        "highTacos": sorted(
            [item for item in items if item["investment"] > 0 and item["tacos"] > 0.03],
            key=lambda item: -item["tacos"],
        ),
        "salesNoAds": sorted(
            [item for item in items if item["units"] > 0 and item["investment"] == 0],
            key=lambda item: -item["totalRevenue"],
        ),
        "skuAds": sorted(
            sku_ads,
            key=lambda item: (-item["investment"], -item["totalRevenue"]),
        ),
        "adsByProduct": sorted(
            decision_items,
            key=lambda item: ((item.get("sku") or "zzz"), -item.get("investment", 0), -item.get("totalRevenue", 0)),
        ),
        "finishedNoSku": sorted(
            finalizados_sem_sku,
            key=lambda item: (-item.get("investment", 0), item.get("code", "")),
        ),
    }


def anonymize_dashboard_data(data):
    demo = copy.deepcopy(data)
    sku_map = {}
    code_map = {}
    title_map = {}
    campaign_map = {}

    def mapped(mapping, value, prefix):
        value = text(value)
        if not value or value == "(sem SKU)":
            return value
        if value not in mapping:
            mapping[value] = f"{prefix} {len(mapping) + 1:03d}"
        return mapping[value]

    def mapped_list(value, mapping, prefix):
        parts = [part.strip() for part in text(value).split(",") if part.strip()]
        if not parts:
            return text(value)
        return ", ".join(mapped(mapping, part.rstrip("."), prefix) for part in parts)

    demo.get("kpis", {})["clientName"] = "Cliente demonstracao"
    for list_name in ("items", "decisionItems", "skuAds", "salesNoAds", "adsNoSales", "highTacos", "adsByProduct", "finishedNoSku"):
        for item in demo.get(list_name, []):
            if item.get("sku"):
                item["sku"] = mapped(sku_map, item.get("sku"), "SKU DEMO")
            if item.get("code"):
                item["code"] = mapped_list(item.get("code"), code_map, "ANUNCIO DEMO")
            if item.get("allCodes"):
                item["allCodes"] = mapped_list(item.get("allCodes"), code_map, "ANUNCIO DEMO")
            if item.get("title"):
                item["title"] = mapped(title_map, item.get("title"), "Produto demonstracao")
            if item.get("campaign"):
                item["campaign"] = mapped_list(item.get("campaign"), campaign_map, "Campanha demo")
            if item.get("adsCampaigns"):
                item["adsCampaigns"] = mapped_list(item.get("adsCampaigns"), campaign_map, "Campanha demo")
            if item.get("allCampaigns"):
                item["allCampaigns"] = mapped_list(item.get("allCampaigns"), campaign_map, "Campanha demo")
            if item.get("relatedActiveCampaigns"):
                item["relatedActiveCampaigns"] = mapped_list(item.get("relatedActiveCampaigns"), campaign_map, "Campanha demo")
    return demo


def render_dashboard(data):
    payload = json.dumps(data, ensure_ascii=False)
    logo_uri = logo_data_uri()
    client_name = data.get("kpis", {}).get("clientName") or ""
    title_suffix = f" - {html.escape(client_name)}" if client_name else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dashboard ADS Mercado Livre{title_suffix}</title>
  <style>
    :root {{
      --bg:#f5f7fb; --card:#fff; --ink:#101828; --muted:#667085; --line:#d9e1ec;
      --blue:#155eef; --green:#07883f; --red:#d92d20; --orange:#b54708; --navy:#102033;
    }}
    * {{ box-sizing:border-box; }}
    html, body {{ min-height:100%; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 Arial, sans-serif; overflow-y:auto; overflow-x:hidden; max-width:100vw; }}
    header {{ position:relative; z-index:5; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); padding:14px 28px; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:18px; }}
    .brand {{ display:flex; align-items:center; gap:14px; min-width:0; }}
    .brand-logo {{ width:58px; height:58px; object-fit:contain; flex:0 0 auto; }}
    h1 {{ margin:0; font-size:22px; }}
    .sub {{ color:var(--muted); margin-top:4px; }}
    main {{ width:min(1500px, calc(100vw - 28px)); margin:0 auto; padding:14px 0 28px; }}
    .kpis {{ display:grid; grid-template-columns:repeat(6,minmax(150px,1fr)); gap:10px; margin-bottom:12px; flex:0 0 auto; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; box-shadow:0 4px 14px rgba(16,24,40,.04); min-width:0; overflow:hidden; }}
    .kpi small {{ color:var(--muted); display:block; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }}
    .kpi strong {{ display:block; font-size:22px; margin-top:6px; }}
    .kpi.danger {{ border-color:#fecdca; }}
    .kpi.good {{ border-color:#abefc6; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    h2 {{ font-size:17px; margin:0 0 12px; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0 10px; background:#fff; border:1px solid var(--line); border-radius:10px; overflow:visible; }}
    th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    thead th {{ position:sticky; top:0; z-index:4; box-shadow:0 2px 0 var(--line); }}
    th {{ background:#f0f4f8; color:#52637a; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
    tbody tr.main-row td {{ border-top:1px solid var(--line); background:#fff; }}
    tbody tr.main-row td:first-child {{ border-left:1px solid var(--line); border-top-left-radius:10px; }}
    tbody tr.main-row td:last-child {{ border-right:1px solid var(--line); border-top-right-radius:10px; }}
    td.num, th.num {{ text-align:right; white-space:nowrap; }}
    .code {{ font-weight:700; }}
    .title {{ color:#344054; max-width:100%; }}
    .text-cell, .title, .decision-text {{ white-space:normal; overflow-wrap:anywhere; word-break:normal; }}
    .pill {{ display:inline-block; padding:4px 8px; border-radius:999px; font-weight:700; font-size:12px; }}
    .Investigar {{ background:#fff1f3; color:#c01048; }}
    .Pausar {{ background:#fef3f2; color:#b42318; }}
    .Otimizar {{ background:#fff7ed; color:#b54708; }}
    .Oportunidade {{ background:#eff8ff; color:#175cd3; }}
    .Manter {{ background:#ecfdf3; color:#067647; }}
    .ManterEscalar {{ background:#ecfdf3; color:#067647; }}
    .abc {{ display:inline-block; min-width:26px; text-align:center; padding:3px 7px; border-radius:6px; font-weight:800; }}
    .abcA {{ background:#dcfae6; color:#067647; }}
    .abcB {{ background:#fef7c3; color:#93370d; }}
    .abcC {{ background:#fee4e2; color:#b42318; }}
    .top-actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
    .primary-action {{ background:var(--navy); color:#fff; border-color:var(--navy); white-space:nowrap; }}
    .secondary-action {{ color:var(--navy); background:#fff; border:1px solid var(--line); padding:9px 12px; border-radius:8px; font-weight:800; text-decoration:none; white-space:nowrap; }}
    .page-nav {{ display:flex; gap:8px; align-items:center; margin:0 0 12px; background:var(--bg); z-index:3; }}
    .page-tab {{ background:#fff; border-color:var(--line); color:#344054; }}
    .page-tab.active {{ background:var(--navy); color:#fff; border-color:var(--navy); }}
    .view {{ display:none; }}
    .view.active {{ display:block; }}
    .abc-panel {{ margin:0; }}
    .abc-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; margin-bottom:10px; }}
    .abc-controls {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
    .abc-summary {{ display:grid; grid-template-columns:repeat(3,minmax(150px,1fr)); gap:10px; margin-bottom:10px; }}
    .abc-bucket {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fbfcfe; }}
    .abc-bucket strong {{ display:block; font-size:18px; margin-bottom:3px; }}
    .bar {{ height:8px; background:#e9eef5; border-radius:999px; overflow:hidden; margin-top:6px; }}
    .bar span {{ display:block; height:100%; background:var(--blue); border-radius:999px; }}
    .version-tag {{ color:#667085; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; margin-top:2px; }}
    .table-card {{ margin-top:0; overflow:hidden; }}
    .scroll-frame {{ height:56vh; min-height:330px; max-height:560px; width:100%; max-width:100%; overflow:auto; border:1px solid var(--line); border-radius:10px; background:#fff; overscroll-behavior:contain; }}
    .scroll-frame table {{ border:0; border-radius:0; margin:0; }}
    .ops-table {{ width:1420px; table-layout:fixed; }}
    .abc-table {{ width:1280px; table-layout:fixed; }}
    .scroll-frame thead th {{ top:0; }}
    .muted {{ color:var(--muted); font-size:12px; }}
    .copyline {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .copybtn {{ border:1px solid var(--line); background:#f8fafc; color:#344054; width:24px; height:24px; padding:0; border-radius:6px; font-size:13px; line-height:1; cursor:pointer; }}
    .copybtn:hover {{ background:#eef4ff; border-color:#b2ccff; }}
    .decision-row td {{ background:#fbfcfe; padding-top:8px; padding-bottom:10px; border-left:1px solid var(--line); border-right:1px solid var(--line); border-bottom:1px solid var(--line); border-bottom-left-radius:10px; border-bottom-right-radius:10px; }}
    .decision-wrap {{ display:grid; grid-template-columns:80px minmax(0,1fr); gap:8px; align-items:start; }}
    .decision-text {{ color:var(--muted); line-height:1.45; }}
    .decision-text b {{ color:#52637a; }}
    .toolbar {{ display:flex; gap:10px; align-items:center; justify-content:space-between; margin:10px 0; }}
    .context-control {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .context-control label {{ color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; }}
    select {{ border:1px solid var(--line); background:#fff; color:var(--ink); padding:9px 36px 9px 12px; border-radius:8px; font-weight:700; min-width:260px; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; }}
    button {{ border:1px solid var(--line); background:#fff; padding:9px 12px; border-radius:8px; font-weight:700; cursor:pointer; }}
    button.active {{ background:var(--navy); color:#fff; }}
    .sortbtn {{ border:0; background:transparent; padding:0; border-radius:0; color:#52637a; font:inherit; font-weight:800; text-transform:uppercase; letter-spacing:.04em; }}
    .sortbtn:hover {{ color:var(--navy); text-decoration:underline; }}
    input {{ width:280px; border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
    .note {{ color:var(--muted); font-size:13px; margin-top:8px; }}
    @media (max-width:1100px) {{ main {{ width:calc(100vw - 16px); }} .kpis {{ grid-template-columns:repeat(2,1fr); }} .grid {{ grid-template-columns:1fr; }} .abc-summary {{ grid-template-columns:1fr; }} .topbar {{ align-items:flex-start; flex-direction:column; }} .scroll-frame {{ height:58vh; max-height:58vh; min-height:300px; }} }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        {f'<img class="brand-logo" src="{logo_uri}" alt="Un Clic Marketplace">' if logo_uri else ''}
        <div>
          <h1>Dashboard ADS Mercado Livre{title_suffix}</h1>
          <div class="sub">Modelo analitico para tomada de decisao: TACOS como criterio principal, ROAS apenas informativo.</div>
          <div class="version-tag">Layout tabelas internas v6</div>
        </div>
      </div>
      <div class="top-actions">
        <a class="secondary-action" href="/">Nova analise</a>
        <button class="secondary-action" id="downloadHtml" type="button">Baixar HTML com dados</button>
        <button class="primary-action" id="exportSales" type="button">Gerar excel de vendas</button>
      </div>
    </div>
  </header>
  <main>
    <section class="kpis" id="kpis"></section>
    <nav class="page-nav" aria-label="Visoes do dashboard">
      <button class="page-tab active" data-view="operational" type="button">Operacional</button>
      <button class="page-tab" data-view="abc" type="button">Curva ABC</button>
    </nav>
    <section class="view active" id="view-operational">
      <section class="grid">
        <div class="card">
          <h2>Alertas principais</h2>
          <div id="alerts"></div>
          <p class="note">A visao de investimento sem vendas usa a receita atribuida pelo ADS. Ela ajuda a evitar TACOS/ROAS falsamente bons.</p>
        </div>
        <div class="card">
          <h2>Leitura auxiliar de CTR e CVR</h2>
          <table>
            <tr><th>Cenario</th><th>Leitura recomendada</th></tr>
            <tr><td>CTR baixo + muitas impressoes</td><td>Revisar imagem, titulo, preco, frete e relevancia.</td></tr>
            <tr><td>CTR alto + sem venda</td><td>Problema provavelmente depois do clique: preco, prazo, reputacao, pagina, variacao ou oferta.</td></tr>
            <tr><td>CTR bom + TACOS saudavel</td><td>Candidato a escala, validando margem e estoque.</td></tr>
            <tr><td>CTR baixo mas vende com TACOS bom</td><td>Nao pausar automaticamente; pode ser produto de nicho ou ticket maior.</td></tr>
            <tr><td>CTR baixo + CVR baixo</td><td>Problema antes e depois do clique; revisar anuncio e oferta.</td></tr>
            <tr><td>CTR alto + CVR baixo</td><td>Anuncio atrai, mas a pagina/oferta nao convence.</td></tr>
            <tr><td>CTR baixo + CVR alto</td><td>Poucos clicam, mas quem clica compra; melhorar atratividade para ganhar volume.</td></tr>
            <tr><td>CVR alto + TACOS ruim</td><td>Vende, mas o clique esta caro ou a margem nao cobre.</td></tr>
            <tr><td>CVR baixo + TACOS bom</td><td>Nao pausar automaticamente; pode ter baixo volume ou ticket alto.</td></tr>
          </table>
        </div>
      </section>
      <div class="toolbar">
        <div class="context-control">
          <label for="contextSelect">Contexto</label>
          <select id="contextSelect">
            <option value="items" selected>Todos os anuncios</option>
            <option value="adsByProduct">Anuncios por produto</option>
            <option value="finishedNoSku">Anuncios finalizados</option>
            <option value="adsNoSales">Investimento sem venda ADS</option>
            <option value="skuAds">Publicidade por SKU</option>
            <option value="highTacos">TACOS acima da meta</option>
            <option value="decisionItems">Todos com decisao</option>
            <option value="salesNoAds">Venda sem ADS</option>
          </select>
        </div>
        <input id="search" placeholder="Buscar SKU, MLB, titulo ou campanha">
      </div>
      <section class="card table-card">
        <h2 id="tableTitle">Todos com decisao</h2>
        <div class="scroll-frame" id="table"></div>
      </section>
    </section>
    <section class="view" id="view-abc">
      <section class="card abc-panel">
        <div class="abc-head">
          <div>
            <h2>Curva ABC de vendas</h2>
            <p class="note">Classifica o que mais pesa no resultado. A fica ate 80% acumulado, B ate 95%, C o restante.</p>
          </div>
          <div class="abc-controls">
            <span class="muted">Ver por</span>
            <button data-abc-mode="sku" class="active" type="button">SKU</button>
            <button data-abc-mode="product" type="button">Anuncio</button>
            <span class="muted">Ordenar por</span>
            <button data-abc-metric="units" type="button">Unidades vendidas</button>
            <button data-abc-metric="totalRevenue" class="active" type="button">Faturamento</button>
            <button data-abc-metric="investment" type="button">Investimento</button>
            <span class="muted">Ordem</span>
            <button data-abc-direction="desc" class="active" type="button">Maior para menor</button>
            <button data-abc-direction="asc" type="button">Menor para maior</button>
          </div>
        </div>
        <div class="abc-summary" id="abcSummary"></div>
        <div class="toolbar">
          <input id="abcSearch" placeholder="Buscar SKU, MLB, titulo ou campanha">
        </div>
        <div class="scroll-frame" id="abcTable"></div>
      </section>
    </section>
  </main>
  <script>
    const DATA = {payload};
    const brl = value => value.toLocaleString('pt-BR', {{ style:'currency', currency:'BRL' }});
    const pct = value => (value * 100).toLocaleString('pt-BR', {{ minimumFractionDigits:2, maximumFractionDigits:2 }}) + '%';
    const num = value => value.toLocaleString('pt-BR', {{ maximumFractionDigits:0 }});
    let current = 'items';
    let sortState = {{ key:'investment', direction:1 }};
    let abcMode = 'sku';
    let abcMetric = 'totalRevenue';
    let abcDirection = 'desc';
    const titles = {{
      items:'Todos os anuncios',
      decisionItems:'Todos com decisao',
      adsNoSales:'Investimento sem venda ADS',
      highTacos:'TACOS acima da meta',
      salesNoAds:'Venda sem ADS',
      skuAds:'Publicidade por SKU',
      adsByProduct:'Anuncios por produto',
      finishedNoSku:'Anuncios finalizados sem SKU'
    }};
    function actionClass(action) {{ return (action || '').split(' ')[0].replace('/', ''); }}
    function abcClass(value) {{ return `abc abc${{value || 'C'}}`; }}
    const abcMetricLabels = {{
      units: 'unidades vendidas',
      totalRevenue: 'faturamento',
      investment: 'investimento'
    }};
    const sortKeys = {{
      sku: item => item.sku || '',
      code: item => item.code || '',
      price: item => item.lastPrice || 0,
      units: item => item.units || 0,
      revenue: item => item.totalRevenue || 0,
      adsRevenue: item => item.adsRevenue || 0,
      investment: item => item.investment || 0,
      cpc: item => item.cpc || 0,
      ctr: item => item.ctr || 0,
      cvr: item => item.cvr || 0,
      tacos: item => item.tacos || 0,
      roas: item => item.roas || 0,
      decision: item => item.action || ''
    }};
    function sortable(label, key) {{
      const active = sortState.key === key ? (sortState.direction === 1 ? ' ▲' : sortState.direction === -1 ? ' ▼' : '') : ' ↕';
      return `<button class="sortbtn" type="button" data-sort="${{key}}">${{label}}${{active}}</button>`;
    }}
    function copyButton(value, label) {{
      const safe = String(value || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
      return value ? `<button class="copybtn" type="button" data-copy="${{safe}}" title="Copiar ${{label}}">⧉</button>` : '';
    }}
    function escapeCell(value) {{
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }}
    function itemSearchText(item) {{
      return [
        item.sku,
        item.code,
        item.allCodes,
        item.title,
        item.campaign,
        item.allCampaigns,
        item.adsCampaigns,
        item.campaignStatus,
        item.action,
        item.alertText
      ].filter(Boolean).join(' ').toLowerCase();
    }}
    function crc32(text) {{
      let table = crc32.table;
      if (!table) {{
        table = crc32.table = Array.from({{ length:256 }}, (_, index) => {{
          let value = index;
          for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
          return value >>> 0;
        }});
      }}
      let crc = -1;
      for (let i = 0; i < text.length; i++) crc = (crc >>> 8) ^ table[(crc ^ text.charCodeAt(i)) & 0xff];
      return (crc ^ -1) >>> 0;
    }}
    function dosDateTime(date) {{
      const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
      const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
      return {{ time, day }};
    }}
    function u16(value) {{ return String.fromCharCode(value & 0xff, (value >>> 8) & 0xff); }}
    function u32(value) {{ return String.fromCharCode(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff); }}
    function zipStore(files) {{
      const now = dosDateTime(new Date());
      let offset = 0;
      const local = [];
      const central = [];
      files.forEach(file => {{
        const name = unescape(encodeURIComponent(file.name));
        const content = unescape(encodeURIComponent(file.content));
        const crc = crc32(content);
        local.push('PK\\x03\\x04' + u16(20) + u16(0) + u16(0) + u16(now.time) + u16(now.day) + u32(crc) + u32(content.length) + u32(content.length) + u16(name.length) + u16(0) + name + content);
        central.push('PK\\x01\\x02' + u16(20) + u16(20) + u16(0) + u16(0) + u16(now.time) + u16(now.day) + u32(crc) + u32(content.length) + u32(content.length) + u16(name.length) + u16(0) + u16(0) + u16(0) + u16(0) + u32(0) + u32(offset) + name);
        offset += 30 + name.length + content.length;
      }});
      const centralText = central.join('');
      return local.join('') + centralText + 'PK\\x05\\x06' + u16(0) + u16(0) + u16(files.length) + u16(files.length) + u32(centralText.length) + u32(offset) + u16(0);
    }}
    function columnName(index) {{
      let name = '';
      let value = index + 1;
      while (value > 0) {{
        const mod = (value - 1) % 26;
        name = String.fromCharCode(65 + mod) + name;
        value = Math.floor((value - mod) / 26);
      }}
      return name;
    }}
    function xlsxCell(value, rowIndex, columnIndex, style = 0) {{
      const ref = `${{columnName(columnIndex)}}${{rowIndex + 1}}`;
      const styleAttr = style ? ` s="${{style}}"` : '';
      if (typeof value === 'number' && Number.isFinite(value)) {{
        return `<c r="${{ref}}"${{styleAttr}}><v>${{value}}</v></c>`;
      }}
      const safe = escapeCell(value);
      return `<c r="${{ref}}" t="inlineStr"${{styleAttr}}><is><t>${{safe}}</t></is></c>`;
    }}
    function makeXlsxBlob(sheetRows) {{
      const sheetData = sheetRows.map((row, rowIndex) => `<row r="${{rowIndex + 1}}">${{row.map((cell, colIndex) => xlsxCell(cell.value, rowIndex, colIndex, cell.style || 0)).join('')}}</row>`).join('');
      const worksheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${{Array.from({{ length:19 }}, (_, i) => `<col min="${{i + 1}}" max="${{i + 1}}" width="${{[14,24,52,12,10,14,12,18,14,18,18,18,10,10,10,10,10,34,18][i]}}" customWidth="1"/>`).join('')}}</cols><sheetData>${{sheetData}}</sheetData></worksheet>`;
      const files = [
        {{ name:'[Content_Types].xml', content:'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>' }},
        {{ name:'_rels/.rels', content:'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>' }},
        {{ name:'xl/workbook.xml', content:'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Vendas ABC" sheetId="1" r:id="rId1"/></sheets></workbook>' }},
        {{ name:'xl/_rels/workbook.xml.rels', content:'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' }},
        {{ name:'xl/styles.xml', content:'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="R$ #,##0.00"/></numFmts><fonts count="3"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="12"/><color rgb="FFFFFFFF"/><name val="Arial"/></font><font><b/><sz val="11"/><color rgb="FF0C5132"/><name val="Arial"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17324D"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDFF3E7"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="8"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right"/></xf><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf><xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>' }},
        {{ name:'xl/worksheets/sheet1.xml', content:worksheet }}
      ];
      const zip = zipStore(files);
      const bytes = Uint8Array.from(zip, char => char.charCodeAt(0));
      return new Blob([bytes], {{ type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }});
    }}
    function abcRows() {{
      const rows = abcMode === 'sku' ? DATA.skuAds : DATA.decisionItems;
      const total = rows.reduce((sum, item) => sum + (item[abcMetric] || 0), 0);
      let cumulative = 0;
      return [...rows]
        .sort((a,b) => abcDirection === 'desc' ? (b[abcMetric] || 0) - (a[abcMetric] || 0) : (a[abcMetric] || 0) - (b[abcMetric] || 0))
        .map((item, index) => {{
          const value = item[abcMetric] || 0;
          cumulative += value;
          const share = total ? value / total : 0;
          const cumulativeShare = total ? cumulative / total : 0;
          return {{
            ...item,
            abcRank: index + 1,
            abcValue: value,
            abcShare: share,
            abcCumulativeShare: cumulativeShare,
            abcClassValue: cumulativeShare <= .80 ? 'A' : cumulativeShare <= .95 ? 'B' : 'C'
          }};
        }});
    }}
    function productRowsForExport() {{
      const rows = DATA.items || DATA.decisionItems;
      const total = rows.reduce((sum, item) => sum + (item[abcMetric] || 0), 0);
      let cumulative = 0;
      return [...rows]
        .sort((a,b) => abcDirection === 'desc' ? (b[abcMetric] || 0) - (a[abcMetric] || 0) : (a[abcMetric] || 0) - (b[abcMetric] || 0))
        .map((item, index) => {{
          const value = item[abcMetric] || 0;
          cumulative += value;
          const cumulativeShare = total ? cumulative / total : 0;
          return {{
            ...item,
            exportRank: index + 1,
            exportClassValue: cumulativeShare <= .80 ? 'A' : cumulativeShare <= .95 ? 'B' : 'C'
          }};
        }});
    }}
    function metricValue(value) {{
      return abcMetric === 'units' ? num(value || 0) : brl(value || 0);
    }}
    function bindCopyButtons() {{
      document.querySelectorAll('[data-copy]').forEach(button => {{
        if (button.dataset.bound === '1') return;
        button.dataset.bound = '1';
        button.addEventListener('click', async () => {{
          const value = button.dataset.copy;
          try {{
            await navigator.clipboard.writeText(value);
            const old = button.textContent;
            button.textContent = 'OK';
            setTimeout(() => button.textContent = old, 900);
          }} catch (error) {{
            const input = document.createElement('textarea');
            input.value = value;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            input.remove();
            const old = button.textContent;
            button.textContent = 'OK';
            setTimeout(() => button.textContent = old, 900);
          }}
        }});
      }});
    }}
    function renderAbc() {{
      const searchInput = document.getElementById('abcSearch');
      const q = searchInput ? searchInput.value.toLowerCase() : '';
      const rows = abcRows().filter(item => JSON.stringify({{
        sku: item.sku,
        code: item.code,
        allCodes: item.allCodes,
        title: item.title,
        campaign: item.campaign,
        allCampaigns: item.allCampaigns,
        adsCampaigns: item.adsCampaigns
      }}).toLowerCase().includes(q));
      const total = rows.reduce((sum, item) => sum + item.abcValue, 0);
      const buckets = ['A','B','C'].map(label => {{
        const bucketRows = rows.filter(item => item.abcClassValue === label);
        const bucketValue = bucketRows.reduce((sum, item) => sum + item.abcValue, 0);
        return {{ label, count: bucketRows.length, value: bucketValue, share: total ? bucketValue / total : 0 }};
      }});
      document.getElementById('abcSummary').innerHTML = buckets.map(bucket => `<div class="abc-bucket">
        <span class="${{abcClass(bucket.label)}}">Classe ${{bucket.label}}</span>
        <strong>${{metricValue(bucket.value)}}</strong>
        <div class="muted">${{bucket.count}} itens - ${{pct(bucket.share)}} do total por ${{abcMetricLabels[abcMetric]}}</div>
        <div class="bar"><span style="width:${{Math.max(3, bucket.share * 100)}}%"></span></div>
      </div>`).join('');
      document.getElementById('abcTable').innerHTML = `<table class="abc-table">
        <colgroup>
          <col style="width:48px"><col style="width:62px"><col style="width:120px"><col style="width:260px"><col style="width:300px">
          <col style="width:120px"><col style="width:110px"><col style="width:110px"><col style="width:76px"><col style="width:120px"><col style="width:110px">
        </colgroup>
        <thead><tr>
          <th class="num">#</th><th>ABC</th><th>SKU</th><th>Anuncio</th><th>Titulo</th>
          <th class="num">${{abcMetricLabels[abcMetric]}}</th><th class="num">Participacao</th><th class="num">Acumulado</th>
          <th class="num">Unid.</th><th class="num">Faturamento</th><th class="num">Invest.</th>
        </tr></thead>
        <tbody>${{rows.map(item => `<tr>
          <td class="num">${{item.abcRank}}</td>
          <td><span class="${{abcClass(item.abcClassValue)}}">${{item.abcClassValue}}</span></td>
          <td><div class="copyline"><span class="code">${{item.sku || '(sem SKU)'}}</span>${{copyButton(item.sku, 'SKU')}}</div></td>
          <td><div class="copyline"><span class="code">${{item.allCodes || item.code || ''}}</span>${{copyButton(item.allCodes || item.code, 'MLB')}}</div></td>
          <td class="text-cell"><div class="title">${{item.title || ''}}</div></td>
          <td class="num">${{metricValue(item.abcValue)}}</td>
          <td class="num">${{pct(item.abcShare)}}</td>
          <td class="num">${{pct(item.abcCumulativeShare)}}</td>
          <td class="num">${{num(item.units || 0)}}</td>
          <td class="num">${{brl(item.totalRevenue || 0)}}</td>
          <td class="num">${{brl(item.investment || 0)}}</td>
        </tr>`).join('')}}</tbody>
      </table>`;
      bindCopyButtons();
    }}
    function exportSalesExcel() {{
      const rows = productRowsForExport();
      const generatedAt = new Date().toLocaleString('pt-BR');
      const totals = rows.reduce((acc, item) => {{
        acc.units += item.units || 0;
        acc.productRevenue += item.productRevenue || item.totalRevenue || 0;
        acc.adsRevenue += item.adsRevenue || 0;
        acc.totalRevenue += item.totalRevenue || 0;
        acc.investment += item.investment || 0;
        return acc;
      }}, {{ units:0, productRevenue:0, adsRevenue:0, totalRevenue:0, investment:0 }});
      const headers = [
        'SKU',
        'Rotulos de Linha',
        'Titulo',
        'Ranking ABC',
        'Classe ABC',
        'Unidades vendidas',
        'Unidades %',
        'Receita por produtos (BRL)',
        'Receita por produtos %',
        'Receita por vendas indiretas',
        'Receita por vendas totais',
        'Investimento (Moeda local)',
        'CTR',
        'CVR',
        'ACOS',
        'TACOS',
        'ROAS',
        'Campanha',
        'Decisao'
      ];
      const body = rows.map(item => {{
        const productRevenue = item.productRevenue || item.totalRevenue || 0;
        const totalRevenue = item.totalRevenue || productRevenue;
        const adsRevenue = item.adsRevenue || 0;
        const investment = item.investment || 0;
        return [
          item.sku || '',
          item.allCodes || item.code || '',
          item.title || '',
          item.exportRank || '',
          item.exportClassValue || '',
          item.units || 0,
          totals.units ? (item.units || 0) / totals.units : 0,
          productRevenue,
          totals.productRevenue ? productRevenue / totals.productRevenue : 0,
          adsRevenue,
          totalRevenue,
          investment,
          item.ctr || 0,
          item.cvr || 0,
          adsRevenue ? investment / adsRevenue : 0,
          totalRevenue ? investment / totalRevenue : 0,
          investment ? adsRevenue / investment : 0,
          item.campaign || item.adsCampaigns || '',
          item.action || ''
        ];
      }});
      const titleRow = [{{ value:'Relatorio de vendas Mercado Livre - Curva ABC', style:1 }}];
      while (titleRow.length < headers.length) titleRow.push({{ value:'', style:1 }});
      const subtitleRow = [{{ value:`Gerado em ${{generatedAt}} | Linha a linha por SKU e MLB | Ordenado por ${{abcMetricLabels[abcMetric]}}`, style:2 }}];
      while (subtitleRow.length < headers.length) subtitleRow.push({{ value:'', style:2 }});
      const totalRow = [
        'Total','','','','',
        totals.units, 1,
        totals.productRevenue, 1,
        totals.adsRevenue, totals.totalRevenue, totals.investment,
        '', '',
        totals.adsRevenue ? totals.investment / totals.adsRevenue : 0,
        totals.totalRevenue ? totals.investment / totals.totalRevenue : 0,
        totals.investment ? totals.adsRevenue / totals.investment : 0,
        '',''
      ].map(value => ({{ value, style:2 }}));
      const headerRow = headers.map(value => ({{ value, style:1 }}));
      const columnStyles = [0,0,0,4,0,4,6,5,6,5,5,5,6,6,6,6,7,0,0];
      const styledTotalRow = totalRow.map((cell, index) => ({{ ...cell, style: index >= 5 && index <= 16 ? columnStyles[index] : cell.style }}));
      const sheetRows = [titleRow, subtitleRow, styledTotalRow, headerRow].concat(body.map(row => row.map((value, index) => ({{ value, style:columnStyles[index] || 0 }}))));
      const blob = makeXlsxBlob(sheetRows);
      const link = document.createElement('a');
      const client = (DATA.kpis.clientName || 'cliente').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      link.href = URL.createObjectURL(blob);
      link.download = `relatorio-vendas-abc-${{client || 'cliente'}}.xlsx`;
      document.body.appendChild(link);
      link.click();
      URL.revokeObjectURL(link.href);
      link.remove();
    }}
    function downloadDashboardHtml() {{
      const source = '<!doctype html>\\n' + document.documentElement.outerHTML;
      const blob = new Blob([source], {{ type:'text/html;charset=utf-8' }});
      const link = document.createElement('a');
      const client = (DATA.kpis.clientName || 'cliente').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      link.href = URL.createObjectURL(blob);
      link.download = `dashboard-ads-mercado-livre-${{client || 'cliente'}}-com-dados.html`;
      document.body.appendChild(link);
      link.click();
      URL.revokeObjectURL(link.href);
      link.remove();
    }}
    function renderKpis() {{
      const k = DATA.kpis;
      document.getElementById('kpis').innerHTML = [
        ['Produtos analisados', num(k.products), ''],
        ['Receita total', brl(k.revenue), 'good'],
        ['Receita atribuida ADS', brl(k.adsRevenue), ''],
        ['Investimento ADS', brl(k.investment), ''],
        ['CVR ADS geral', pct(k.cvr), ''],
        ['TACOS geral', pct(k.tacos), k.tacos > .03 ? 'danger' : 'good'],
        ['ROAS geral', k.roas.toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}}), ''],
        ['Investiu sem venda ADS', num(k.adsNoSales), k.adsNoSales ? 'danger' : 'good'],
        ['Valor sem venda ADS', brl(k.investmentNoAdsSales), k.investmentNoAdsSales ? 'danger' : 'good']
      ].map(([label,value,cls]) => `<div class="card kpi ${{cls}}"><small>${{label}}</small><strong>${{value}}</strong></div>`).join('');
    }}
    function renderAlerts() {{
      const k = DATA.kpis;
      document.getElementById('alerts').innerHTML = `<table>
        <tr><th>Alerta</th><th class="num">Qtd.</th><th>Leitura</th></tr>
        <tr><td>Investimento sem venda atribuida no ADS</td><td class="num">${{k.adsNoSales}}</td><td>${{brl(k.investmentNoAdsSales)}} gastos sem venda atribuida.</td></tr>
        <tr><td>Investimento em item sem venda total</td><td class="num">${{k.adsOnlyNoTotalSales}}</td><td>Pode nao aparecer na planilha final atual.</td></tr>
        <tr><td>TACOS acima de 3%</td><td class="num">${{k.tacosHigh}}</td><td>Acima da meta definida.</td></tr>
        <tr><td>Venda sem investimento</td><td class="num">${{k.salesNoAds}}</td><td>Possivel oportunidade, se margem permitir.</td></tr>
      </table>`;
    }}
    function row(item) {{
      return `<tr class="main-row">
        <td><div class="copyline"><span class="code">${{item.sku || '(sem SKU)'}}</span>${{copyButton(item.sku, 'SKU')}}</div><div class="muted">${{item.adCount ? item.adCount + ' anuncios' : ''}}</div></td>
        <td class="text-cell"><div class="copyline"><span class="code">${{item.allCodes || item.code}}</span>${{copyButton(item.allCodes || item.code, 'MLB')}}</div><div class="title">${{item.title || ''}}</div></td>
        <td><span class="${{abcClass(item.abcSku)}}">SKU ${{item.abcSku || 'C'}}</span><div class="muted"><span class="${{abcClass(item.abcCode)}}">MLB ${{item.abcCode || '-'}}</span></div></td>
        <td class="text-cell">${{item.campaign || item.adsCampaigns || ''}}<div class="muted">${{item.campaignStatus || ''}}</div></td>
        <td class="num">${{item.lastPrice ? brl(item.lastPrice) : '-'}}<div class="muted">${{item.avgSalePrice ? 'media: ' + brl(item.avgSalePrice) : ''}}</div><div class="muted">${{item.priceMin && item.priceMax && item.priceMin !== item.priceMax ? 'menor/maior SKU: ' + brl(item.priceMin) + ' a ' + brl(item.priceMax) : (item.lastSaleDate ? 'ultima venda: ' + item.lastSaleDate : '')}}</div></td>
        <td class="num">${{num(item.units || 0)}}</td>
        <td class="num">${{brl(item.totalRevenue || 0)}}</td>
        <td class="num">${{brl(item.adsRevenue || 0)}}</td>
        <td class="num">${{brl(item.investment || 0)}}</td>
        <td class="num">${{brl(item.cpc || 0)}}<div class="muted">max ${{brl(item.maxCpc || 0)}}</div></td>
        <td class="num">${{pct(item.ctr || 0)}}<div class="muted">${{item.ctrClass || ''}}</div></td>
        <td class="num">${{pct(item.cvr || 0)}}<div class="muted">${{item.cvrClass || ''}}</div></td>
        <td class="num">${{pct(item.tacos || 0)}}</td>
        <td class="num">${{(item.roas || 0).toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}})}}</td>
      </tr>
      <tr class="decision-row">
        <td colspan="14">
          <div class="decision-wrap">
            <span class="pill ${{actionClass(item.action)}}">${{item.action}}</span>
            <div class="decision-text"><b>Alertas:</b> ${{item.alertText || 'Sem alerta'}}<br><b>Leitura:</b> ${{item.recommendation || item.reason}}</div>
          </div>
        </td>
      </tr>`;
    }}
    function renderTable() {{
      const q = document.getElementById('search').value.toLowerCase();
      let rows = DATA[current].filter(item => itemSearchText(item).includes(q));
      if (sortState.key && sortState.direction !== 0) {{
        const getter = sortKeys[sortState.key];
        rows = [...rows].sort((a,b) => {{
          const av = getter(a);
          const bv = getter(b);
          if (typeof av === 'number' || typeof bv === 'number') {{
            return sortState.direction === 1 ? (bv - av) : (av - bv);
          }}
          return sortState.direction === 1
            ? String(bv).localeCompare(String(av), 'pt-BR')
            : String(av).localeCompare(String(bv), 'pt-BR');
        }});
      }}
      document.getElementById('tableTitle').textContent = titles[current] + ` (${{rows.length}})`;
      document.getElementById('table').innerHTML = `<table class="ops-table">
        <colgroup>
          <col style="width:110px"><col style="width:300px"><col style="width:86px"><col style="width:165px"><col style="width:120px"><col style="width:64px"><col style="width:108px">
          <col style="width:108px"><col style="width:96px"><col style="width:84px"><col style="width:78px"><col style="width:78px"><col style="width:78px"><col style="width:70px">
        </colgroup>
        <thead><tr>
          <th>${{sortable('SKU','sku')}}</th><th>${{sortable('Anuncio','code')}}</th><th>ABC</th><th>Campanha</th><th class="num">${{sortable('Ult. preco','price')}}</th><th class="num">${{sortable('Unid.','units')}}</th><th class="num">${{sortable('Receita','revenue')}}</th>
          <th class="num">${{sortable('Receita ADS','adsRevenue')}}</th><th class="num">${{sortable('Invest.','investment')}}</th><th class="num">${{sortable('CPC','cpc')}}</th><th class="num">${{sortable('CTR','ctr')}}</th><th class="num">${{sortable('CVR','cvr')}}</th><th class="num">${{sortable('TACOS','tacos')}}</th><th class="num">${{sortable('ROAS','roas')}}</th>
        </tr></thead>
        <tbody>${{rows.map(row).join('')}}</tbody>
      </table>`;
      document.querySelectorAll('[data-copy]').forEach(button => {{
        if (button.dataset.bound === '1') return;
        button.dataset.bound = '1';
        button.addEventListener('click', async () => {{
          const value = button.dataset.copy;
          try {{
            await navigator.clipboard.writeText(value);
            const old = button.textContent;
            button.textContent = '✓';
            setTimeout(() => button.textContent = old, 900);
          }} catch (error) {{
            const input = document.createElement('textarea');
            input.value = value;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            input.remove();
            const old = button.textContent;
            button.textContent = '✓';
            setTimeout(() => button.textContent = old, 900);
          }}
        }});
      }});
      document.querySelectorAll('[data-sort]').forEach(button => {{
        button.addEventListener('click', () => {{
          const key = button.dataset.sort;
          if (sortState.key !== key) {{
            sortState = {{ key, direction: 1 }};
          }} else if (sortState.direction === 1) {{
            sortState.direction = -1;
          }} else {{
            sortState = {{ key:null, direction:0 }};
          }}
          renderTable();
        }});
      }});
    }}
    document.querySelectorAll('button[data-tab]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button[data-tab]').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        current = button.dataset.tab;
        sortState = {{ key:'investment', direction:1 }};
        renderTable();
      }});
    }});
    document.querySelectorAll('button[data-view]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button[data-view]').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(`view-${{button.dataset.view}}`).classList.add('active');
      }});
    }});
    document.getElementById('contextSelect').addEventListener('change', event => {{
      current = event.target.value;
      sortState = {{ key:'investment', direction:1 }};
      renderTable();
    }});
    document.querySelectorAll('button[data-abc-mode]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button[data-abc-mode]').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        abcMode = button.dataset.abcMode;
        renderAbc();
      }});
    }});
    document.querySelectorAll('button[data-abc-metric]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button[data-abc-metric]').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        abcMetric = button.dataset.abcMetric;
        renderAbc();
      }});
    }});
    document.querySelectorAll('button[data-abc-direction]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('button[data-abc-direction]').forEach(b => b.classList.remove('active'));
        button.classList.add('active');
        abcDirection = button.dataset.abcDirection;
        renderAbc();
      }});
    }});
    document.getElementById('exportSales').addEventListener('click', exportSalesExcel);
    document.getElementById('downloadHtml').addEventListener('click', downloadDashboardHtml);
    document.getElementById('search').addEventListener('input', renderTable);
    document.getElementById('abcSearch').addEventListener('input', renderAbc);
    renderKpis(); renderAbc(); renderAlerts(); renderTable();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    print("Use abrir_dashboard_ads_ml_corrigido.bat para iniciar o app atualizado em http://127.0.0.1:4182")
