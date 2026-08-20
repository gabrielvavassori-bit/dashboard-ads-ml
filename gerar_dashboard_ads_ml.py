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
TACOS_TARGET = 0.03
ADS_DEPENDENCY_ATTENTION = 0.35
ADS_DEPENDENCY_HIGH = 0.50
ADS_DEPENDENCY_CRITICAL = 0.70

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


def deduplicate_ads_rows(ads_rows):
    deduped_rows = []
    seen = {}
    duplicate_examples = []
    removed_rows = 0
    removed_revenue = 0.0
    removed_investment = 0.0
    removed_clicks = 0.0
    removed_impressions = 0.0
    removed_sales = 0.0

    for row_number, row in ads_rows:
        if row_number < 3:
            deduped_rows.append((row_number, row))
            continue
        code = text(row.get(5)).upper()
        if not code.startswith("MLB"):
            deduped_rows.append((row_number, row))
            continue
        key = tuple(row.get(col, "") for col in range(1, 21))
        first_seen_row = seen.get(key)
        if first_seen_row is not None:
            removed_rows += 1
            removed_revenue += number(row.get(12))
            removed_investment += number(row.get(13))
            removed_impressions += number(row.get(7))
            removed_clicks += number(row.get(8))
            removed_sales += number(row.get(18))
            if len(duplicate_examples) < 12:
                duplicate_examples.append({
                    "code": code,
                    "campaign": text(row.get(3)),
                    "status": text(row.get(6)),
                    "firstRow": first_seen_row,
                    "removedRow": row_number,
                    "adsRevenue": number(row.get(12)),
                    "investment": number(row.get(13)),
                })
            continue
        seen[key] = row_number
        deduped_rows.append((row_number, row))
    return deduped_rows, {
        "hasDuplicates": removed_rows > 0,
        "removedRows": removed_rows,
        "removedRevenue": removed_revenue,
        "removedInvestment": removed_investment,
        "removedImpressions": removed_impressions,
        "removedClicks": removed_clicks,
        "removedAdsSales": removed_sales,
        "examples": duplicate_examples,
    }


def detect_ads_period(ads_rows):
    date_from = None
    date_to = None
    months = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}
    for row_number, row in ads_rows:
        if row_number < 3:
            continue
        raw_from = text(row.get(1))
        raw_to = text(row.get(2))
        match_from = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", raw_from)
        if match_from and match_from.group(2).lower() in months:
            parsed_from = datetime(int(match_from.group(3)), months[match_from.group(2).lower()], int(match_from.group(1)))
            date_from = parsed_from if date_from is None or parsed_from < date_from else date_from
        match_to = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", raw_to)
        if match_to and match_to.group(2).lower() in months:
            parsed_to = datetime(int(match_to.group(3)), months[match_to.group(2).lower()], int(match_to.group(1)))
            date_to = parsed_to if date_to is None or parsed_to > date_to else date_to
    return {
        "dateFrom": date_from.strftime("%Y-%m-%d") if date_from else "",
        "dateTo": date_to.strftime("%Y-%m-%d") if date_to else "",
    }


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


def ads_dependency_state(ratio):
    ratio = ratio or 0
    if ratio >= ADS_DEPENDENCY_CRITICAL:
        return "critical"
    if ratio >= ADS_DEPENDENCY_HIGH:
        return "high"
    if ratio >= ADS_DEPENDENCY_ATTENTION:
        return "attention"
    return "healthy"


def ads_dependency_label(ratio):
    return {
        "critical": "Dependencia Ads critica",
        "high": "Dependencia Ads alta",
        "attention": "Dependencia Ads em atencao",
        "healthy": "Dependencia Ads saudavel",
    }[ads_dependency_state(ratio)]


def confidence_label(item):
    score = 0
    reasons = []
    validations = []
    clicks = item.get("clicks", 0) or 0
    impressions = item.get("impressions", 0) or 0
    ads_sales = item.get("adsSales", 0) or 0
    units = item.get("units", 0) or 0
    if clicks >= 80:
        score += 2
        reasons.append("volume de cliques forte")
    elif clicks >= 30:
        score += 1
        reasons.append("volume de cliques suficiente")
    else:
        validations.append("amostra de cliques ainda pequena")
    if impressions >= 1000:
        score += 1
        reasons.append("boa exposicao")
    elif impressions:
        validations.append("impressoes ainda limitadas")
    if ads_sales >= 3 or units >= 5:
        score += 1
        reasons.append("base de vendas minimamente consistente")
    elif ads_sales or units:
        validations.append("base de vendas ainda curta")
    if item.get("possibleCatalog") or (item.get("adCount", 0) or 0) > 1:
        score -= 2
        validations.append("mais de um MLB no agrupamento; conferir anuncio por anuncio")
    if item.get("salesCoverageComplete") is False:
        score -= 2
        validations.append("snapshot de vendas parcial; faturamento e TACOS ainda nao estao fechados")
    if score >= 3:
        return "forte", reasons or ["base consistente"], validations
    if score >= 1:
        return "provavel", reasons or ["ha sinais uteis"], validations
    return "hipotese", reasons or ["sinais inconclusivos"], validations


def diagnosis_hypotheses(item):
    hypotheses = []
    investment = item.get("investment", 0) or 0
    ads_revenue = item.get("adsRevenue", 0) or 0
    ctr_label = item.get("ctrClass", "")
    cvr_label = item.get("cvrClass", "")
    if investment > 0 and ads_revenue <= 0:
        hypotheses.append("o gasto nao mostrou retorno atribuivel; revisar campanha, termos e anuncio")
    if ctr_label == "Baixo" and (item.get("impressions", 0) or 0) >= 1000:
        hypotheses.append("baixa atratividade no resultado de busca: imagem principal, titulo ou oferta")
    if ctr_label in ("Bom", "Otimo") and cvr_label in ("Sem conversao", "Baixa"):
        hypotheses.append("o problema mais provavel esta depois do clique: pagina, preco, prazo ou variacao")
    if cvr_label in ("Muito boa", "Excelente") and (item.get("tacos", 0) or 0) > TACOS_TARGET:
        hypotheses.append("o item vende, mas o custo da campanha esta pesado para a receita total")
    if (item.get("adsDependencyRatio", 0) or 0) >= ADS_DEPENDENCY_HIGH:
        hypotheses.append("o produto depende de ADS e merece reforco organico para reduzir risco")
    if item.get("possibleCatalog"):
        hypotheses.append("a leitura agregada pode esconder diferenca entre MLBs do mesmo SKU")
    return list(dict.fromkeys(hypotheses))[:5] or ["sem hipotese dominante alem da leitura principal"]


def suggested_test_order(item):
    steps = []
    ctr_label = item.get("ctrClass", "")
    cvr_label = item.get("cvrClass", "")
    if ctr_label == "Baixo" and (item.get("impressions", 0) or 0) >= 1000:
        steps.extend(["testar primeiro a imagem principal", "depois testar o titulo", "em seguida validar preco e oferta"])
        if (item.get("investment", 0) or 0) > 0:
            steps.append("so depois revisar campanha, segmentacao e amplitude do trafego")
    elif ctr_label in ("Bom", "Otimo") and cvr_label in ("Sem conversao", "Baixa"):
        steps.extend(["validar primeiro preco, oferta e reputacao", "depois revisar pagina e variacoes"])
    elif cvr_label in ("Muito boa", "Excelente") and (item.get("tacos", 0) or 0) > TACOS_TARGET:
        steps.extend(["testar primeiro verba, CPC e segmentacao", "depois revisar oferta se o custo continuar pesado"])
    if (item.get("adsDependencyRatio", 0) or 0) >= ADS_DEPENDENCY_HIGH:
        steps.append("trabalhar ganho organico antes de escalar mais verba")
    if not steps:
        steps = [part.strip(" .") for part in str(item.get("recommendation") or item.get("reason") or "Monitorar").split("|") if part.strip()]
    return list(dict.fromkeys(steps))[:5]


def reading_summary(item):
    if item.get("salesCoverageComplete") is False:
        return "leitura parcial: Ads esta atualizado, mas o faturamento ainda nao terminou de ser coletado"
    investment = item.get("investment", 0) or 0
    ads_revenue = item.get("adsRevenue", 0) or 0
    if investment > 0 and (item.get("totalRevenue", 0) or 0) <= 0:
        return "gasto detectado sem venda total no cruzamento atual"
    if investment > 0 and ads_revenue <= 0:
        return "gasto sem venda ADS atribuida; desperdicio provavel ate validacao"
    if item.get("ctrClass") == "Baixo" and item.get("cvrClass") in ("Boa", "Muito boa", "Excelente"):
        return "atratividade fraca, mas pos-clique saudavel"
    if item.get("ctrClass") in ("Bom", "Otimo") and item.get("cvrClass") in ("Sem conversao", "Baixa"):
        return "anuncio chama clique, mas a oferta nao fecha bem"
    if (item.get("tacos", 0) or 0) > TACOS_TARGET and item.get("cvrClass") in ("Muito boa", "Excelente"):
        return "produto converte, mas o custo da verba esta pesado"
    if item.get("possibleCatalog"):
        return "leitura agregada pode esconder diferenca entre anuncios do mesmo SKU"
    return "leitura intermediaria; cruzar oferta, campanha e anuncio antes de concluir"


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
    ads_dependency = item.get("adsDependencyRatio", 0) or 0

    ctr_label = ctr_class(ctr * 100)
    cvr_label = cvr_class(cvr * 100)
    item["ctrClass"] = ctr_label
    item["cvrClass"] = cvr_label
    item["adsDependencyState"] = ads_dependency_state(ads_dependency)
    item["adsDependencyLabel"] = ads_dependency_label(ads_dependency)

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
    if total_revenue > 0 and ads_dependency >= ADS_DEPENDENCY_CRITICAL:
        alerts.append("Dependencia critica de ADS")
        recommendations.append("Validar pagina, SEO interno e oferta para reduzir risco comercial.")
    elif total_revenue > 0 and ads_dependency >= ADS_DEPENDENCY_HIGH:
        alerts.append("Dependencia alta de ADS")
        recommendations.append("Trabalhar ganho organico antes de escalar verba.")
    elif total_revenue > 0 and ads_dependency >= ADS_DEPENDENCY_ATTENTION:
        alerts.append("Dependencia de ADS em atencao")
        recommendations.append("Acompanhar se a pagina sustenta venda organica.")
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
    confidence, reasons, validations = confidence_label(item)
    item["confidence"] = confidence
    item["confidenceReasons"] = reasons
    item["validationPoints"] = validations
    item["diagnosticSummary"] = reading_summary(item)
    item["diagnosisHypotheses"] = diagnosis_hypotheses(item)
    item["testOrder"] = suggested_test_order(item)


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


def mark_condition_context(items):
    condition_codes = {}
    for item in items:
        user_product_id = str(item.get("userProductId") or item.get("user_product_id") or "").strip()
        code = str(item.get("code") or "").strip()
        if user_product_id and code:
            condition_codes.setdefault(user_product_id, set()).add(code)

    for item in items:
        user_product_id = str(item.get("userProductId") or item.get("user_product_id") or "").strip()
        catalog_product_id = str(item.get("catalogProductId") or item.get("catalog_product_id") or "").strip()
        codes = sorted(condition_codes.get(user_product_id, set())) if user_product_id else []
        item["userProductId"] = user_product_id
        item["catalogProductId"] = catalog_product_id
        item["catalogListing"] = bool(item.get("catalogListing") or item.get("catalog_listing"))
        item["conditionCodes"] = codes
        item["conditionCount"] = len(codes)
        item["conditionLabel"] = (
            f"{user_product_id} · {len(codes)} opcao(oes)"
            if user_product_id
            else "Sem vinculo MLBU"
        )
        item["catalogLabel"] = (
            f"Catalogo {catalog_product_id}"
            if catalog_product_id
            else ("Catalogo sincronizado" if item["catalogListing"] else "Fora do catalogo")
        )


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
            "children": [],
            "condition_keys": set(),
            "catalog_product_ids": set(),
            "thumbnailUrl": "",
            "thumbnailCount": 0,
            "thumbnailRevenue": -1,
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
            "orders": 0,
            "units": 0,
            "productRevenue": 0,
            "totalRevenue": 0,
            "adsRevenue": 0,
            "adsDirectRevenue": 0,
            "adsIndirectRevenue": 0,
            "organicRevenue": 0,
            "tacosBaseRevenue": 0,
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
            "salesCoverageComplete": True,
        })
        if item.get("code"):
            target["codes"].add(item["code"])
        target["children"].append(item)
        if item.get("campaign") and item["campaign"] != "Inativo":
            target["campaigns"].add(item["campaign"])
        if item.get("adsCampaigns") and item["adsCampaigns"] != item.get("campaign"):
            target["campaigns"].add(item["adsCampaigns"])
        if item.get("userProductId"):
            target["condition_keys"].add(item["userProductId"])
        if item.get("catalogProductId"):
            target["catalog_product_ids"].add(item["catalogProductId"])
        if item.get("thumbnailUrl"):
            target["thumbnailCount"] += 1
            if (item.get("totalRevenue", 0) or 0) > target["thumbnailRevenue"]:
                target["thumbnailUrl"] = item["thumbnailUrl"]
                target["thumbnailRevenue"] = item.get("totalRevenue", 0) or 0
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
        target["orders"] += item.get("orders", 0) or 0
        target["units"] += item.get("units", 0) or 0
        target["productRevenue"] += item.get("productRevenue", 0) or 0
        target["totalRevenue"] += item.get("totalRevenue", 0) or 0
        target["adsRevenue"] += item.get("adsRevenue", 0) or 0
        target["adsDirectRevenue"] += item.get("adsDirectRevenue", 0) or 0
        target["adsIndirectRevenue"] += item.get("adsIndirectRevenue", 0) or 0
        target["organicRevenue"] += item.get("organicRevenue", 0) or 0
        target["tacosBaseRevenue"] += item.get("tacosBaseRevenue", item.get("totalRevenue", 0)) or 0
        target["investment"] += item.get("investment", 0) or 0
        target["impressions"] += item.get("impressions", 0) or 0
        target["clicks"] += item.get("clicks", 0) or 0
        target["adsSales"] += item.get("adsSales", 0) or 0
        target["salesCoverageComplete"] = target["salesCoverageComplete"] and item.get("salesCoverageComplete") is not False

    result = []
    for item in grouped.values():
        codes = sorted(item.pop("codes"))
        campaigns = sorted(item.pop("campaigns"))
        condition_keys = sorted(item.pop("condition_keys"))
        catalog_product_ids = sorted(item.pop("catalog_product_ids"))
        item.pop("thumbnailRevenue", None)
        item["allCodes"] = ", ".join(codes)
        item["possibleCatalog"] = item.get("possibleCatalog", False) or len(codes) > 1
        item["allCampaigns"] = ", ".join(campaigns)
        item["code"] = ", ".join(codes[:4]) + ("..." if len(codes) > 4 else "")
        item["adCount"] = len(codes)
        item["campaign"] = ", ".join(campaigns[:3]) + ("..." if len(campaigns) > 3 else "")
        item["conditionLabel"] = ", ".join(condition_keys[:2]) + ("..." if len(condition_keys) > 2 else "") if condition_keys else "Sem vinculo MLBU"
        item["catalogLabel"] = ", ".join(catalog_product_ids[:2]) + ("..." if len(catalog_product_ids) > 2 else "") if catalog_product_ids else "Sem catalogo identificado"
        item["tacos"] = item["investment"] / item["tacosBaseRevenue"] if item["tacosBaseRevenue"] else 0
        item["roas"] = item["adsRevenue"] / item["investment"] if item["investment"] else 0
        item["adsDependencyRatio"] = item["adsDirectRevenue"] / item["totalRevenue"] if item["totalRevenue"] else 0
        item["outsideAdsRatio"] = item["organicRevenue"] / item["totalRevenue"] if item["totalRevenue"] else 0
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


def aggregate_by_campaign(items):
    campaigns_by_code = {}
    for item in items:
        code = item.get("code") or ""
        campaign = item.get("campaign") or item.get("adsCampaigns") or "(sem campanha)"
        if code:
            campaigns_by_code.setdefault(code, set()).add(campaign)

    grouped = {}
    for item in items:
        campaign = item.get("campaign") or item.get("adsCampaigns") or "(sem campanha)"
        target = grouped.setdefault(campaign, {
            "campaignKey": campaign,
            "campaign": campaign,
            "campaignStatus": "Inativo",
            "sku": "",
            "code": "",
            "skus": set(),
            "codes": set(),
            "condition_keys": set(),
            "catalog_product_ids": set(),
            "thumbnailUrl": "",
            "thumbnailCount": 0,
            "children": [],
            "orders": 0,
            "units": 0,
            "productRevenue": 0,
            "totalRevenue": 0,
            "adsRevenue": 0,
            "adsDirectRevenue": 0,
            "adsIndirectRevenue": 0,
            "organicRevenue": 0,
            "tacosBaseRevenue": 0,
            "investment": 0,
            "impressions": 0,
            "clicks": 0,
            "adsSales": 0,
            "possibleCatalog": False,
            "salesCoverageComplete": True,
            "campaignRevenueAmbiguous": False,
        })
        target["children"].append(copy.deepcopy(item))
        if item.get("sku"):
            target["skus"].add(item["sku"])
        if item.get("code"):
            target["codes"].add(item["code"])
            if len(campaigns_by_code.get(item["code"], set())) > 1:
                target["campaignRevenueAmbiguous"] = True
        if item.get("userProductId"):
            target["condition_keys"].add(item["userProductId"])
        if item.get("catalogProductId"):
            target["catalog_product_ids"].add(item["catalogProductId"])
        if item.get("thumbnailUrl"):
            target["thumbnailCount"] += 1
        if item.get("campaignStatus") == "Ativa":
            target["campaignStatus"] = "Ativa"
        target["possibleCatalog"] = target["possibleCatalog"] or bool(item.get("possibleCatalog"))
        target["salesCoverageComplete"] = target["salesCoverageComplete"] and item.get("salesCoverageComplete") is not False
        for field in (
            "orders", "units", "productRevenue", "totalRevenue", "adsRevenue", "adsDirectRevenue",
            "adsIndirectRevenue", "organicRevenue", "tacosBaseRevenue", "investment",
            "impressions", "clicks", "adsSales",
        ):
            target[field] += item.get(field, 0) or 0

    result = []
    for item in grouped.values():
        item["children"].sort(key=lambda row: (-(row.get("investment", 0) or 0), -(row.get("totalRevenue", 0) or 0)))
        item["skus"] = sorted(item["skus"])
        item["codes"] = sorted(item["codes"])
        condition_keys = sorted(item.pop("condition_keys"))
        catalog_product_ids = sorted(item.pop("catalog_product_ids"))
        item["skuCount"] = len(item["skus"])
        item["adCount"] = len(item["codes"])
        item["sku"] = ", ".join(item["skus"][:3]) + ("..." if len(item["skus"]) > 3 else "") if item["skus"] else "(sem SKU)"
        item["code"] = ", ".join(item["codes"][:4]) + ("..." if len(item["codes"]) > 4 else "")
        item["allCodes"] = ", ".join(item["codes"])
        item["allSkus"] = ", ".join(item["skus"])
        item["conditionLabel"] = ", ".join(condition_keys[:2]) + ("..." if len(condition_keys) > 2 else "") if condition_keys else "Sem vinculo MLBU"
        item["catalogLabel"] = ", ".join(catalog_product_ids[:2]) + ("..." if len(catalog_product_ids) > 2 else "") if catalog_product_ids else "Sem catalogo identificado"
        item["title"] = f"{item['skuCount']} SKU(s), {item['adCount']} anuncio(s)"
        item["tacos"] = item["investment"] / item["tacosBaseRevenue"] if item["tacosBaseRevenue"] else 0
        item["roas"] = item["adsRevenue"] / item["investment"] if item["investment"] else 0
        item["adsDependencyRatio"] = item["adsDirectRevenue"] / item["totalRevenue"] if item["totalRevenue"] else 0
        item["outsideAdsRatio"] = item["organicRevenue"] / item["totalRevenue"] if item["totalRevenue"] else 0
        item["ctr"] = item["clicks"] / item["impressions"] if item["impressions"] else 0
        item["cvr"] = item["adsSales"] / item["clicks"] if item["clicks"] else 0
        item["cpc"] = item["investment"] / item["clicks"] if item["clicks"] else 0
        item["avgAdsOrder"] = item["adsRevenue"] / item["adsSales"] if item["adsSales"] else 0
        item["maxCpc"] = item["avgAdsOrder"] * TACOS_TARGET * item["cvr"] if item["avgAdsOrder"] and item["cvr"] else 0
        item["topInvestmentLabel"] = ""
        top = max(item["children"], key=lambda row: row.get("investment", 0) or 0, default=None)
        if top:
            item["topInvestmentLabel"] = f"{top.get('sku') or '(sem SKU)'} - {top.get('code') or ''}".strip(" -")
            item["thumbnailUrl"] = top.get("thumbnailUrl") or ""
        item["adsNoSalesCount"] = len([
            row for row in item["children"]
            if (row.get("investment", 0) or 0) > 0 and (row.get("adsRevenue", 0) or 0) <= 0
        ])
        apply_alerts(item)
        if item["campaignRevenueAmbiguous"]:
            item["confidence"] = "hipotese"
            item["validationPoints"] = list(dict.fromkeys([
                "o mesmo MLB aparece em mais de uma campanha; o faturamento comercial nao pode ser atribuido a uma campanha com seguranca",
                *item.get("validationPoints", []),
            ]))
        item["action"], item["reason"] = decision(item)
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
    ads_period = detect_ads_period(ads_rows)
    ads_rows, ads_deduplication = deduplicate_ads_rows(ads_rows)
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
            "adsDirectRevenue": 0,
            "adsIndirectRevenue": 0,
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
        target["adsDirectRevenue"] += number(row.get(19))
        target["adsIndirectRevenue"] += number(row.get(20))
        target["investment"] += number(row.get(13))
        target["adsSales"] += number(row.get(18))

    items = []
    for code, item in sales.items():
        ad = ads.get(code, {})
        item = dict(item)
        ads_direct_revenue = ad.get("adsDirectRevenue", 0) or 0
        ads_indirect_revenue = ad.get("adsIndirectRevenue", 0) or 0
        ads_total_revenue = ads_direct_revenue + ads_indirect_revenue
        if ads_total_revenue <= 0:
            ads_total_revenue = ad.get("adsRevenue", item["indirectRevenue"]) or 0
        item["adsDirectRevenue"] = ads_direct_revenue
        item["adsIndirectRevenue"] = ads_indirect_revenue
        item["adsRevenue"] = ads_total_revenue
        item["adsInvestmentRaw"] = ad.get("investment", item["investment"])
        item["indirectRevenue"] = item.get("indirectRevenue", 0)
        item["totalRevenue"] = item["productRevenue"]
        item["investment"] = ad.get("investment", item["investment"])
        item["organicRevenue"] = max(0, (item["totalRevenue"] or 0) - (item["adsDirectRevenue"] or 0))
        item["tacosBaseRevenue"] = (item["organicRevenue"] or 0) + (item["adsDirectRevenue"] or 0) + (item["adsIndirectRevenue"] or 0)
        item["tacos"] = item["investment"] / item["tacosBaseRevenue"] if item["tacosBaseRevenue"] else 0
        item["roas"] = item["adsRevenue"] / item["investment"] if item["investment"] else 0
        item["revenueOutsideAds"] = item["organicRevenue"]
        item["adsDependencyRatio"] = ((item["adsDirectRevenue"] or 0) / item["totalRevenue"]) if item["totalRevenue"] else 0
        item["outsideAdsRatio"] = (item["organicRevenue"] / item["totalRevenue"]) if item["totalRevenue"] else 0
        item["adsAttributedRatio"] = ((item["adsRevenue"] or 0) / item["totalRevenue"]) if item["totalRevenue"] else 0
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
            ads_only_indirect = ad.get("adsIndirectRevenue", 0) or 0
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
                "tacos": ad["investment"] / ads_only_indirect if ads_only_indirect else 0,
                "roas": 0,
                "adsDirectRevenue": ad.get("adsDirectRevenue", 0) or 0,
                "adsIndirectRevenue": ad.get("adsIndirectRevenue", 0) or 0,
                "organicRevenue": 0,
                "tacosBaseRevenue": ads_only_indirect,
                "revenueOutsideAds": 0,
                "adsDependencyRatio": 0,
                "outsideAdsRatio": 0,
                "adsAttributedRatio": 0,
                "campaign": ", ".join(sorted(ad["campaigns"])),
                "campaignStatus": "Ativa" if ad.get("activeCampaigns") else "Sem campanha ativa",
                "adsRevenue": ((ad.get("adsDirectRevenue", 0) or 0) + (ad.get("adsIndirectRevenue", 0) or 0)) or ad["adsRevenue"],
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
    mark_condition_context(all_decision_items)
    apply_sku_campaign_context(all_decision_items)
    for item in all_decision_items:
        apply_alerts(item)
        action, reason = decision(item)
        item["action"] = action
        item["reason"] = reason
    sku_ads = aggregate_by_sku(all_decision_items)
    campaign_ads = aggregate_by_campaign(all_decision_items)
    apply_abc(all_decision_items, "totalRevenue", "abcCode")
    apply_abc(sku_ads, "totalRevenue", "abcSku")
    apply_abc(campaign_ads, "totalRevenue", "abcCampaign")
    sku_abc = {item["sku"]: item["abcSku"] for item in sku_ads}
    for item in all_decision_items:
        item["abcSku"] = sku_abc.get(item.get("sku") or "(sem SKU)", "C")
    finalizados_sem_sku = [item for item in all_decision_items if not item.get("sku")]
    decision_items = [item for item in all_decision_items if item.get("sku")]
    total_revenue = sum(item["totalRevenue"] for item in items)
    total_investment = sum(item["investment"] for item in items)
    total_ads_revenue = sum(item.get("adsRevenue", 0) for item in items)
    total_ads_direct_revenue = sum(item.get("adsDirectRevenue", 0) for item in items)
    total_organic_revenue = max(0, total_revenue - total_ads_direct_revenue)
    total_tacos_base_revenue = total_revenue
    total_clicks = sum(item.get("clicks", 0) for item in all_decision_items)
    total_ads_sales = sum(item.get("adsSales", 0) for item in all_decision_items)
    kpis = {
        "clientName": client_name,
        "salesSource": sales_source,
        "products": len(items),
        "units": sum(item["units"] for item in items),
        "revenue": total_revenue,
        "adsRevenue": total_ads_revenue,
        "adsDirectRevenue": total_ads_direct_revenue,
        "organicRevenue": total_organic_revenue,
        "tacosBaseRevenue": total_tacos_base_revenue,
        "investment": total_investment,
        "investmentNoAdsSales": sum(item["investment"] for item in all_decision_items if item["investment"] > 0 and item.get("adsRevenue", 0) <= 0),
        "cvr": total_ads_sales / total_clicks if total_clicks else 0,
        "tacos": total_investment / total_tacos_base_revenue if total_tacos_base_revenue else 0,
        "roas": total_ads_revenue / total_investment if total_investment else 0,
        "adsNoSales": len([item for item in all_decision_items if item["investment"] > 0 and item.get("adsRevenue", 0) <= 0]),
        "adsOnlyNoTotalSales": len(ads_only),
        "tacosHigh": len([item for item in items if item["investment"] > 0 and item["tacos"] > 0.03]),
        "salesNoAds": len([item for item in items if item["units"] > 0 and item["investment"] == 0]),
    }
    return {
        "kpis": kpis,
        "meta": {
            "period": ads_period,
            "adsDeduplication": ads_deduplication,
        },
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
        "campaignAds": sorted(
            campaign_ads,
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
    for list_name in ("items", "decisionItems", "skuAds", "campaignAds", "salesNoAds", "adsNoSales", "highTacos", "adsByProduct", "finishedNoSku"):
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
    online_mode = ((data.get("meta") or {}).get("onlineMode") or {})
    online_notice = html.escape(str(online_mode.get("notice") or ""))
    online_period = online_mode.get("onlinePeriod") or {}
    period_mode = str(online_period.get("mode") or "30d")
    period_month = html.escape(str(online_period.get("month") or ""))
    period_from = html.escape(str(online_period.get("dateFrom") or ""))
    period_to = html.escape(str(online_period.get("dateTo") or ""))
    period_compare = str(online_period.get("compareMode") or "none")
    period_warning = html.escape(str(online_period.get("warning") or ""))
    period_labels = {
        "today": "Hoje",
        "yesterday": "Ontem",
        "7d": "Ultimos 7 dias",
        "15d": "Ultimos 15 dias",
        "30d": "Ultimos 30 dias",
        "month": "Por mes",
        "custom": "Personalizado",
    }
    compare_labels = {
        "none": "Nao comparar",
        "previous": "Periodo anterior",
        "previous_month": "Mesmo periodo do mes anterior",
        "previous_year": "Mesmo periodo do ano anterior",
    }
    period_label = html.escape(period_labels.get(period_mode, "Periodo selecionado"))
    compare_label = html.escape(compare_labels.get(period_compare, "Nao comparar"))

    def period_option(value, label):
        selected = " selected" if period_mode == value else ""
        return f'<option value="{value}"{selected}>{label}</option>'

    def compare_option(value, label):
        selected = " selected" if period_compare == value else ""
        return f'<option value="{value}"{selected}>{label}</option>'

    online_period_filter = ""
    if online_mode.get("enabled"):
        online_period_filter = f"""
    <details class="card period-picker">
      <summary>
        <span><strong>Periodo:</strong> {period_label} <span class="period-summary-meta">{period_from} a {period_to}</span></span>
        <span class="period-summary-meta">Comparacao: {compare_label}</span>
      </summary>
      <div class="period-popover">
      <form class="period-form" method="get" action="/online" data-online-period-form>
        <input type="hidden" name="confirmed" value="1">
        <label>Periodo<select name="period" data-online-period>{period_option('today', 'Hoje')}{period_option('yesterday', 'Ontem')}{period_option('7d', 'Ultimos 7 dias')}{period_option('15d', 'Ultimos 15 dias')}{period_option('30d', 'Ultimos 30 dias')}{period_option('month', 'Por mes')}{period_option('custom', 'Personalizado')}</select></label>
        <div class="field-group" id="period-month-field" hidden>
          <label>Mes<input type="month" name="month" value="{period_month}"></label>
        </div>
        <div class="field-group" id="period-custom-fields" hidden>
          <label>Data inicial<input type="date" name="date_from" value="{period_from}"></label>
          <label>Data final<input type="date" name="date_to" value="{period_to}"></label>
        </div>
        <label>Comparar com<select name="compare">{compare_option('none', 'Nao comparar')}{compare_option('previous', 'Periodo anterior')}{compare_option('previous_month', 'Mesmo periodo do mes anterior')}{compare_option('previous_year', 'Mesmo periodo do ano anterior')}</select></label>
        <button class="primary-action" type="submit">Aplicar periodo</button>
      </form>
      <p class="note">Hoje usa dados parciais. Os demais periodos fecham em ontem. Para comparar, escolha uma opcao e aplique novamente.</p>
        {f'<div class="period-warning">{period_warning}</div>' if period_warning else ''}
      </div>
    </details>
    <script>
    (() => {{
      const form = document.querySelector('[data-online-period-form]');
      const select = document.querySelector('[data-online-period]');
      const month = document.getElementById('period-month-field');
      const custom = document.getElementById('period-custom-fields');
      if (!form || !select) return;
      const sync = () => {{
        if (month) month.hidden = select.value !== 'month';
        if (custom) custom.hidden = select.value !== 'custom';
      }};
      select.addEventListener('change', () => {{
        sync();
        if (select.value !== 'month' && select.value !== 'custom') form.submit();
      }});
      sync();
    }})();
    </script>
    """
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
    tbody.product-group {{ outline:2px solid #84adff; outline-offset:-2px; background:#f8fbff; }}
    tbody.product-group tr td:first-child {{ border-left:1px solid #84adff; }}
    tbody.product-group tr td:last-child {{ border-right:1px solid #84adff; }}
    tbody.product-group tr.product-parent-row td {{ background:#eaf2ff; border-top:2px solid #5b8def; font-weight:700; }}
    tbody.product-group tr.product-child-row td {{ background:#fff; }}
    tbody.product-group tr.product-group-note td {{ background:#f5f8ff; border-bottom:2px solid #84adff; color:#344054; }}
    tbody.product-group tr.product-parent-row td:first-child {{ border-top-left-radius:8px; }}
    tbody.product-group tr.product-parent-row td:last-child {{ border-top-right-radius:8px; }}
    tbody.product-group tr.product-group-note td:first-child {{ border-bottom-left-radius:8px; }}
    tbody.product-group tr.product-group-note td:last-child {{ border-bottom-right-radius:8px; }}
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
    .table-card-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:12px; }}
    .table-card-head h2 {{ margin:0; }}
    .table-display-controls {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .table-display-controls .muted {{ font-weight:700; }}
    .table-zoom-value {{ min-width:48px; text-align:center; font-weight:800; color:#344054; }}
    .table-help {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-top:14px; padding:14px; border:1px solid #d7e3f7; border-radius:10px; background:#f8fbff; }}
    .table-help strong {{ display:block; margin-bottom:4px; }}
    .table-help p {{ margin:0; color:#52637a; }}
    .table-help-side {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:flex-end; text-align:right; }}
    .whatsapp-support {{ position:fixed; right:22px; bottom:22px; z-index:40; display:flex; align-items:center; gap:9px; padding:11px 14px; border-radius:999px; background:#25d366; color:#fff; font-weight:800; text-decoration:none; box-shadow:0 8px 24px rgba(16,24,40,.22); }}
    .whatsapp-support:hover {{ background:#1fb95a; transform:translateY(-1px); }}
    .whatsapp-support svg {{ width:24px; height:24px; flex:0 0 auto; fill:currentColor; }}
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
    .toolbar-left {{ display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }}
    .control-block {{ display:flex; flex-direction:column; gap:5px; }}
    .control-block > label {{ color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; }}
    .segmented {{ display:flex; gap:0; }}
    .segmented button {{ border-radius:0; min-width:84px; }}
    .segmented button:first-child {{ border-radius:8px 0 0 8px; }}
    .segmented button:last-child {{ border-radius:0 8px 8px 0; }}
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
    .beta-grid {{ display:grid; grid-template-columns:repeat(4,minmax(180px,1fr)); gap:10px; margin-bottom:12px; }}
    .status-ok {{ color:var(--green); font-weight:800; }}
    .status-warn {{ color:var(--orange); font-weight:800; }}
    .status-bad {{ color:var(--red); font-weight:800; }}
    .online-notice {{ margin:0 0 12px; padding:12px 14px; border:1px solid #fecdca; border-radius:10px; background:#fff7ed; color:#7a271a; font-weight:700; }}
    .decision-wrap {{ grid-template-columns:minmax(0,1fr) auto; align-items:center; }}
    .decision-summary-main, .decision-summary-side {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .decision-teaser {{ color:var(--muted); }}
    .summary-chip {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#f2f4f7; color:#344054; font-size:12px; font-weight:800; }}
    .product-thumbnail {{ position:relative; width:52px; height:52px; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#f8fafc; display:flex; align-items:center; justify-content:center; color:#98a2b3; font-size:9px; font-weight:800; text-align:center; line-height:1.1; }}
    .product-thumbnail img {{ width:100%; height:100%; display:block; object-fit:contain; background:#fff; }}
    .product-thumbnail-count {{ position:absolute; right:2px; bottom:2px; min-width:20px; padding:2px 4px; border-radius:999px; background:rgba(16,32,51,.9); color:#fff; font-size:9px; line-height:1.2; }}
    .detail-row td {{ background:#fbfcfe; border:1px solid var(--line); border-top:0; }}
    .detail-grid {{ display:grid; grid-template-columns:repeat(3,minmax(260px,1fr)); gap:12px; }}
    .detail-block {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:#fff; }}
    .detail-block h3 {{ font-size:14px; margin:0 0 8px; }}
    .detail-block ul {{ margin:0; padding-left:18px; }}
    .detail-block li {{ margin:4px 0; }}
    .detail-block-wide {{ grid-column:1/-1; }}
    .listing-facts {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:8px; }}
    .listing-fact {{ border:1px solid var(--line); border-radius:8px; padding:9px; background:#f8fafc; }}
    .listing-fact b {{ display:block; margin-top:3px; color:var(--ink); }}
    .readonly-badge {{ display:inline-block; margin-bottom:8px; padding:4px 8px; border-radius:999px; background:#eef4ff; color:#1849a9; font-size:12px; font-weight:800; }}
    .price-signal {{ border-left:4px solid var(--orange); }}
    .daily-chart-card {{ position:relative; overflow:hidden; padding:16px; background:linear-gradient(180deg,#fff 0%,#fbfdff 100%); }}
    .chart-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:14px; flex-wrap:wrap; }}
    .chart-head h3 {{ margin-bottom:4px; font-size:16px; }}
    .chart-summary {{ color:var(--muted); font-size:12px; }}
    .chart-metric-tabs {{ display:flex; gap:6px; padding:4px; border:1px solid var(--line); border-radius:11px; background:#f8fafc; flex-wrap:wrap; }}
    .chart-metric-button {{ border:0; padding:7px 11px; border-radius:8px; background:transparent; color:#475467; font-size:12px; }}
    .chart-metric-button:hover {{ background:#eef4ff; color:#1849a9; }}
    .chart-metric-button.active {{ background:#102033; color:#fff; box-shadow:0 3px 8px rgba(16,32,51,.16); }}
    .chart-stage {{ position:relative; min-height:270px; border:1px solid #e4e7ec; border-radius:12px; background:#fff; overflow:hidden; }}
    .chart-canvas {{ width:100%; min-height:270px; }}
    .daily-chart {{ width:100%; min-height:270px; display:block; overflow:visible; }}
    .chart-grid {{ stroke:#e4e7ec; stroke-width:1; stroke-dasharray:4 5; }}
    .chart-average-line {{ stroke:#f79009; stroke-width:2; stroke-dasharray:7 6; }}
    .chart-average-label {{ fill:#b54708; font-size:11px; font-weight:800; }}
    .chart-reference-line {{ stroke:#175cd3; stroke-width:2; stroke-dasharray:3 5; }}
    .chart-reference-label {{ fill:#1849a9; font-size:11px; font-weight:800; }}
    .chart-axis {{ fill:#667085; font-size:11px; }}
    .chart-bar {{ transition:opacity .15s ease; }}
    .chart-hit {{ fill:transparent; cursor:crosshair; }}
    .chart-hit:hover + .chart-hover-line {{ opacity:1; }}
    .chart-hover-line {{ opacity:0; stroke:#98a2b3; stroke-width:1; stroke-dasharray:3 3; pointer-events:none; }}
    .chart-tooltip {{ position:absolute; z-index:4; min-width:170px; max-width:220px; padding:10px 12px; border:1px solid #d0d5dd; border-radius:10px; background:rgba(255,255,255,.98); box-shadow:0 12px 26px rgba(16,24,40,.18); color:#101828; font-size:12px; line-height:1.45; pointer-events:none; opacity:0; transform:translateX(-50%); transition:opacity .12s ease; }}
    .chart-tooltip.visible {{ opacity:1; }}
    .chart-tooltip b {{ display:block; margin-bottom:4px; font-size:13px; }}
    .chart-tooltip-row {{ display:flex; justify-content:space-between; gap:14px; }}
    .chart-tooltip-row.active {{ color:#175cd3; font-weight:800; }}
    .chart-extreme-label {{ fill:#b42318; font-size:10px; font-weight:900; }}
    .chart-extreme-marker {{ fill:#d92d20; stroke:#fff; stroke-width:1.5; }}
    .campaign-config-grid {{ display:grid; grid-template-columns:repeat(4,minmax(145px,1fr)); gap:8px; margin:0 0 12px; }}
    .campaign-config-card {{ border:1px solid #dbe5f5; border-radius:10px; padding:9px 11px; background:#f8fbff; }}
    .campaign-config-card span {{ display:block; color:#667085; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; }}
    .campaign-config-card b {{ display:block; margin-top:3px; color:#102033; font-size:14px; }}
    .campaign-config-inline {{ margin-top:3px; color:#1849a9; font-size:11px; font-weight:700; }}
    .listing-badges {{ display:flex; gap:4px; flex-wrap:wrap; margin-top:5px; }}
    .listing-mini-badge {{ display:inline-flex; align-items:center; padding:3px 6px; border-radius:999px; background:#f2f4f7; color:#475467; font-size:10px; line-height:1.2; font-weight:800; }}
    .listing-mini-badge.premium {{ background:#fff4e5; color:#b54708; }}
    .listing-mini-badge.classic {{ background:#eef4ff; color:#1849a9; }}
    .listing-mini-badge.shipping-on {{ background:#ecfdf3; color:#027a48; }}
    .listing-mini-badge.shipping-off {{ background:#fef3f2; color:#b42318; }}
    .child-table {{ margin-top:10px; border-spacing:0; }}
    .child-table th, .child-table td {{ font-size:12px; }}
      .period-picker {{ position:relative; z-index:30; margin:0 0 12px; overflow:visible; }}
      .period-picker summary {{ list-style:none; cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; padding:14px 16px; }}
      .period-picker summary::-webkit-details-marker {{ display:none; }}
      .period-picker summary::after {{ content:'▾'; color:var(--muted); font-size:16px; }}
      .period-picker[open] summary::after {{ content:'▴'; }}
      .period-summary-meta {{ color:var(--muted); font-size:12px; font-weight:600; }}
      .period-popover {{ position:absolute; z-index:20; right:0; top:calc(100% + 8px); width:min(560px, calc(100vw - 32px)); padding:16px; background:var(--card); border:1px solid var(--line); border-radius:12px; box-shadow:0 12px 30px rgba(15,23,42,.16); }}
      .period-form {{ display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }}
      .period-form label {{ display:flex; flex-direction:column; gap:5px; color:var(--muted); font-size:12px; font-weight:800; }}
      .period-form select, .period-form input {{ min-width:160px; width:auto; }}
      .period-form input {{ width:160px; }}
      .period-form button {{ align-self:flex-end; }}
      .period-form .field-group {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; width:100%; }}
      .period-form .field-group[hidden] {{ display:none; }}
      .period-warning {{ margin-top:10px; color:var(--orange); font-weight:800; }}
      @media (max-width:700px) {{ .period-popover {{ position:static; width:auto; }} .period-form {{ align-items:stretch; }} .period-form label, .period-form select, .period-form input, .period-form button {{ width:100%; min-width:0; }} .period-form .field-group {{ grid-template-columns:1fr; }} }}
    @media (max-width:1100px) {{ main {{ width:calc(100vw - 16px); }} .kpis {{ grid-template-columns:repeat(2,1fr); }} .grid {{ grid-template-columns:1fr; }} .abc-summary {{ grid-template-columns:1fr; }} .topbar {{ align-items:flex-start; flex-direction:column; }} .scroll-frame {{ height:58vh; max-height:58vh; min-height:300px; }} .detail-grid {{ grid-template-columns:1fr; }} .listing-facts {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .table-help {{ flex-direction:column; }} .table-help-side {{ justify-content:flex-start; text-align:left; }} .chart-head {{ align-items:stretch; }} .chart-metric-tabs {{ width:100%; }} .chart-metric-button {{ flex:1 1 auto; }} .campaign-config-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .whatsapp-support span {{ display:none; }} .whatsapp-support {{ right:14px; bottom:14px; padding:12px; }} }}
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
    {f'<section class="online-notice">{online_notice}</section>' if online_notice else ''}
    {online_period_filter}
    <section class="kpis" id="kpis"></section>
    <nav class="page-nav" aria-label="Visoes do dashboard">
      <button class="page-tab active" data-view="operational" type="button">Operacional</button>
      <button class="page-tab" data-view="abc" type="button">Curva ABC</button>
      <button class="page-tab" data-view="online-beta" type="button">Online Beta</button>
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
        <div class="toolbar-left">
          <div class="control-block">
            <label for="contextSelect">Contexto / filtro de analise</label>
            <select id="contextSelect">
              <option value="all" selected>Todos os itens</option>
              <option value="active">Publicidade ativa</option>
              <option value="ended">Publicidade encerrada</option>
              <option value="noReturn">Gasto sem retorno ADS</option>
              <option value="highTacos">TACOS fora da meta</option>
              <option value="adsDependency">Dependencia de Ads &gt; 50%</option>
              <option value="attention">Requer atencao</option>
              <option value="opportunity">Oportunidade para anunciar</option>
            </select>
          </div>
          <div class="control-block">
            <label>Visualizar por</label>
            <div class="segmented" id="viewMode">
              <button class="active" data-view-mode="mlb" type="button">MLB</button>
              <button data-view-mode="sku" type="button">SKU</button>
              <button data-view-mode="campaign" type="button">Campanha</button>
            </div>
          </div>
        </div>
        <input id="search" placeholder="Buscar SKU, MLB, titulo ou campanha">
      </div>
      <section class="card table-card">
        <div class="table-card-head">
          <h2 id="tableTitle">Todos com decisao</h2>
          <div class="table-display-controls" aria-label="Tamanho da tabela">
            <span class="muted">Tamanho da tabela</span>
            <button id="tableZoomOut" type="button" title="Diminuir tabela">-</button>
            <span class="table-zoom-value" id="tableZoomValue">100%</span>
            <button id="tableZoomIn" type="button" title="Aumentar tabela">+</button>
            <button id="tableZoomFit" type="button">Ajustar a largura</button>
            <button id="tableZoomReset" type="button">Restaurar</button>
          </div>
        </div>
        <div class="scroll-frame" id="table"></div>
        <div class="table-help">
          <div>
            <strong>Como interpretar esta tabela</strong>
            <p id="tableHelpText">O produto pai consolida valores absolutos e recalcula as taxas. Cada filho preserva os dados do anuncio e da condicao de venda.</p>
          </div>
          <div class="table-help-side">
            <span class="muted" id="tableHelpMeta"></span>
            <button class="secondary-action" id="tableTop" type="button">Voltar ao topo</button>
          </div>
        </div>
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
    <section class="view" id="view-online-beta">
      <section class="card">
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap">
          <div>
            <h2>Online Beta</h2>
            <p class="note">Leitura somente consulta para comparar o XLSX com o dado autenticado do cliente no agente-ml. Nao altera cache, campanha nem planilha.</p>
          </div>
          <div class="muted" id="onlineBetaPeriod"></div>
        </div>
        <div class="beta-grid" id="onlineBetaSummary"></div>
        <div id="onlineBetaStatus" class="note"></div>
        <div class="scroll-frame" id="onlineBetaTable" style="margin-top:12px"></div>
      </section>
    </section>
  </main>
  <a class="whatsapp-support" href="https://wa.me/5511998397385?text=Oi%2C%20estou%20precisando%20de%20suporte%20no%20Dash%20Ads." target="_blank" rel="noopener noreferrer" aria-label="Pedir suporte pelo WhatsApp">
    <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M19.11 17.21c-.26-.13-1.54-.76-1.78-.85-.24-.09-.41-.13-.59.13-.17.26-.67.85-.82 1.02-.15.17-.3.2-.56.07-.26-.13-1.09-.4-2.08-1.28-.77-.68-1.29-1.53-1.44-1.79-.15-.26-.02-.4.11-.53.12-.12.26-.3.39-.46.13-.15.17-.26.26-.43.09-.17.04-.33-.02-.46-.07-.13-.59-1.41-.8-1.93-.21-.51-.43-.44-.59-.45h-.5c-.17 0-.46.07-.7.33-.24.26-.91.89-.91 2.17s.93 2.52 1.06 2.69c.13.17 1.83 2.8 4.44 3.93.62.27 1.1.43 1.48.55.62.2 1.19.17 1.64.1.5-.07 1.54-.63 1.76-1.24.22-.61.22-1.13.15-1.24-.06-.12-.23-.18-.49-.31zM16.04 3.2A12.73 12.73 0 0 0 5.2 22.6L3.4 29.2l6.76-1.77a12.72 12.72 0 1 0 5.88-24.23zm0 22.88c-2.03 0-4.02-.55-5.75-1.59l-.41-.24-4.01 1.05 1.07-3.91-.27-.4a10.16 10.16 0 1 1 9.37 5.09z"/></svg>
    <span>Suporte pelo WhatsApp</span>
  </a>
  <script>
    const DATA = {payload};
    const brl = value => value.toLocaleString('pt-BR', {{ style:'currency', currency:'BRL' }});
    const pct = value => (value * 100).toLocaleString('pt-BR', {{ minimumFractionDigits:2, maximumFractionDigits:2 }}) + '%';
    const num = value => value.toLocaleString('pt-BR', {{ maximumFractionDigits:0 }});
    const safe = value => String(value || '').replace(/[&<>"]/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[ch]));
    function saoPauloDateParts(value) {{
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return null;
      const parts = new Intl.DateTimeFormat('pt-BR', {{
        timeZone:'America/Sao_Paulo', year:'numeric', month:'2-digit', day:'2-digit'
      }}).formatToParts(date);
      return Object.fromEntries(parts.filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    }}
    function formatLastSaleDate(value, nowValue = new Date()) {{
      if (!value) return '';
      const date = new Date(value);
      const sale = saoPauloDateParts(date);
      const today = saoPauloDateParts(nowValue);
      if (!sale || !today) return String(value);
      const saleDay = Date.UTC(Number(sale.year), Number(sale.month) - 1, Number(sale.day));
      const todayDay = Date.UTC(Number(today.year), Number(today.month) - 1, Number(today.day));
      const elapsedDays = Math.round((todayDay - saleDay) / 86400000);
      if (elapsedDays === 0) return 'hoje';
      if (elapsedDays === 1) return 'ontem';
      const weekday = new Intl.DateTimeFormat('pt-BR', {{ timeZone:'America/Sao_Paulo', weekday:'long' }}).format(date);
      const month = new Intl.DateTimeFormat('pt-BR', {{ timeZone:'America/Sao_Paulo', month:'long' }}).format(date);
      return `${{weekday.charAt(0).toUpperCase() + weekday.slice(1)}}, ${{sale.day}} de ${{month}} de ${{sale.year}}`;
    }}
    let currentContext = 'all';
    let currentViewMode = 'mlb';
    let tableZoom = (() => {{
      try {{ return Number(localStorage.getItem('dashboardAdsTableZoom')) || 1; }} catch (error) {{ return 1; }}
    }})();
    const detailExpanded = new Set();
    const dailyChartMetric = new Map();
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
    const viewLabels = {{ mlb:'MLB', sku:'SKU', campaign:'Campanha' }};
    const contextLabels = {{
      all:'Todos os itens', active:'Publicidade ativa', ended:'Publicidade encerrada',
      noReturn:'Gasto sem retorno ADS', highTacos:'TACOS fora da meta',
      adsDependency:'Dependencia de Ads > 50%', attention:'Requer atencao',
      opportunity:'Oportunidade para anunciar'
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
      price: item => item.currentPrice || item.lastPrice || 0,
      orders: item => item.orders || 0,
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
      const ownText = [
        item.sku,
        item.code,
        item.allCodes,
        item.title,
        item.campaign,
        item.allCampaigns,
        item.adsCampaigns,
        item.campaignStatus,
        item.userProductId,
        item.catalogProductId,
        item.conditionLabel,
        item.catalogLabel,
        item.action,
        item.alertText
      ].filter(Boolean).join(' ');
      const childText = (item.children || []).map(child => [
        child.sku, child.code, child.title, child.campaign, child.adsCampaigns,
        child.userProductId, child.catalogProductId, child.conditionLabel, child.catalogLabel
      ].filter(Boolean).join(' ')).join(' ');
      return `${{ownText}} ${{childText}}`.toLowerCase();
    }}
    function applyTableZoom() {{
      const table = document.querySelector('#table .ops-table');
      if (table) table.style.zoom = String(tableZoom);
      const label = document.getElementById('tableZoomValue');
      if (label) label.textContent = `${{Math.round(tableZoom * 100)}}%`;
    }}
    function setTableZoom(value, persist = true) {{
      tableZoom = Math.max(.65, Math.min(1.15, Number(value) || 1));
      if (persist) {{
        try {{ localStorage.setItem('dashboardAdsTableZoom', String(tableZoom)); }} catch (error) {{}}
      }}
      applyTableZoom();
    }}
    function stepTableZoom(direction) {{
      const steps = [.65, .75, .85, 1, 1.15];
      const currentIndex = steps.reduce((best, value, index) => Math.abs(value - tableZoom) < Math.abs(steps[best] - tableZoom) ? index : best, 0);
      setTableZoom(steps[Math.max(0, Math.min(steps.length - 1, currentIndex + direction))]);
    }}
    function fitTableToWidth() {{
      const frame = document.getElementById('table');
      const table = frame ? frame.querySelector('.ops-table') : null;
      if (!frame || !table) return;
      table.style.zoom = '1';
      requestAnimationFrame(() => setTableZoom(Math.min(1, (frame.clientWidth - 4) / Math.max(table.scrollWidth, 1))));
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
        ['Receita organica estimada', brl(k.organicRevenue || 0), ''],
        ['Investimento ADS', brl(k.investment), ''],
        ['Base TACOS comercial', brl(k.tacosBaseRevenue || 0), ''],
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
        <td class="text-cell">${{item.campaign || item.adsCampaigns || ''}}<div class="muted">${{item.campaignStatus || ''}}</div>${{campaignConfigInline(item)}}</td>
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
    function legacyRenderTable() {{
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
          <th>${{sortable('SKU','sku')}}</th><th>${{sortable('Anuncio','code')}}</th><th>ABC</th><th>Campanha</th><th class="num">${{sortable('Preco','price')}}</th><th class="num">${{sortable('Unid.','units')}}</th><th class="num">${{sortable('Receita','revenue')}}</th>
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
    function rowsByViewMode() {{
      if (currentViewMode === 'sku') return DATA.skuAds || [];
      if (currentViewMode === 'campaign') return DATA.campaignAds || [];
      return DATA.items || [];
    }}
    function matchesContext(item, context = currentContext) {{
      const status = String(item.campaignStatus || '').toLowerCase();
      if (context === 'active') return status.startsWith('ativa');
      if (context === 'ended') return !status.startsWith('ativa');
      if (context === 'noReturn') return (item.investment || 0) > 0 && (item.adsRevenue || 0) <= 0;
      if (context === 'highTacos') return (item.investment || 0) > 0 && (item.tacos || 0) > .03;
      if (context === 'adsDependency') return (item.adsDependencyRatio || 0) > .50;
      if (context === 'attention') return !String(item.action || '').startsWith('Manter') || (item.alerts || []).length > 1;
      if (context === 'opportunity') return (item.units || 0) > 0 && (item.investment || 0) === 0;
      return true;
    }}
    function renderAlerts() {{
      const rows = rowsByViewMode();
      const stats = [
        ['Todos os itens', rows.length, 'Base completa da visao atual.'],
        ['Publicidade ativa', rows.filter(item => matchesContext(item, 'active')).length, 'Itens com campanha ativa no periodo.'],
        ['Publicidade encerrada', rows.filter(item => matchesContext(item, 'ended')).length, 'Itens sem campanha ativa no periodo.'],
        ['Gasto sem retorno ADS', rows.filter(item => matchesContext(item, 'noReturn')).length, 'Houve gasto, mas nao houve receita ADS atribuida.'],
        ['TACOS fora da meta', rows.filter(item => matchesContext(item, 'highTacos')).length, 'Itens com TACOS acima da meta de 3%.'],
        ['Dependencia de Ads > 50%', rows.filter(item => matchesContext(item, 'adsDependency')).length, 'Mais de 50% da receita direta veio de ADS.'],
        ['Requer atencao', rows.filter(item => matchesContext(item, 'attention')).length, 'Itens com alerta relevante ou acao de revisao.'],
        ['Oportunidade para anunciar', rows.filter(item => matchesContext(item, 'opportunity')).length, 'Venda no periodo sem investimento ADS.']
      ];
      document.getElementById('alerts').innerHTML = `<table>
        <tr><th>Filtro de analise</th><th class="num">Qtd.</th><th>Leitura</th></tr>
        ${{stats.map(stat => `<tr><td>${{safe(stat[0])}}</td><td class="num">${{num(stat[1])}}</td><td>${{safe(stat[2])}}</td></tr>`).join('')}}
      </table>`;
    }}
    function detailKey(item) {{
      return [currentViewMode, item.campaignKey || item.campaign || '', item.sku || '', item.code || ''].join('|');
    }}
    function listBlock(title, rows) {{
      const values = (rows || []).filter(Boolean);
      return `<div class="detail-block"><h3>${{safe(title)}}</h3>${{values.length ? `<ul>${{values.map(value => `<li>${{safe(value)}}</li>`).join('')}}</ul>` : '<div class="muted">Sem informacao adicional.</div>'}}</div>`;
    }}
    function campaignChildren(item) {{
      const children = item.children || [];
      if (!children.length) return '';
      return `<div class="detail-block" style="grid-column:1/-1"><h3>Itens da campanha</h3><table class="child-table">
        <thead><tr><th>SKU</th><th>Anuncio</th><th>Condicao/opcao</th><th>Titulo</th><th class="num">Pedidos</th><th class="num">Unidades</th><th class="num">Receita</th><th class="num">Receita ADS</th><th class="num">Invest.</th><th class="num">CTR</th><th class="num">CVR</th><th class="num">TACOS</th><th>Alerta</th></tr></thead>
        <tbody>${{children.map(child => `<tr><td>${{safe(child.sku || '(sem SKU)')}}</td><td>${{safe(child.code || '')}}</td><td>${{safe(child.conditionLabel || 'Sem vinculo MLBU')}}<div class="muted">${{safe(child.catalogLabel || '')}}</div></td><td>${{safe(child.title || '')}}</td><td class="num">${{num(child.orders || 0)}}</td><td class="num">${{num(child.units || 0)}}</td><td class="num">${{brl(child.totalRevenue || 0)}}</td><td class="num">${{brl(child.adsRevenue || 0)}}</td><td class="num">${{brl(child.investment || 0)}}</td><td class="num">${{pct(child.ctr || 0)}}</td><td class="num">${{pct(child.cvr || 0)}}</td><td class="num">${{pct(child.tacos || 0)}}</td><td>${{safe(child.alertText || 'Sem alerta')}}</td></tr>`).join('')}}</tbody>
      </table></div>`;
    }}
    function listingTypeLabel(value) {{
      const labels = {{ gold_pro:'Premium', gold_premium:'Premium', gold_special:'Classico', gold:'Classico' }};
      return labels[String(value || '').toLowerCase()] || (value ? String(value) : 'Nao informado pelo cache');
    }}
    function logisticLabel(value) {{
      const labels = {{ fulfillment:'Full', cross_docking:'Coleta', xd_drop_off:'Agencia/coleta', drop_off:'Agencia' }};
      return labels[String(value || '').toLowerCase()] || (value ? String(value) : 'Nao informado pelo cache');
    }}
    function dailySeriesFor(item) {{
      const sources = (item.children && item.children.length) ? item.children : [item];
      const byDate = new Map();
      sources.forEach(source => (source.dailySeries || []).forEach(row => {{
        const date = String(row.date || '');
        if (!date) return;
        const current = byDate.get(date) || {{date, orders:0, units:0, revenue:0, adsRevenue:0, adsDirectRevenue:0, adsIndirectRevenue:0, investment:0, tacosBaseRevenue:0, impressions:0, clicks:0, adsUnits:0, priceFallback:0}};
        current.orders += Number(row.orders || 0);
        current.units += Number(row.units || 0);
        current.revenue += Number(row.revenue || 0);
        current.adsRevenue += Number(row.adsRevenue || 0);
        current.adsDirectRevenue += Number(row.adsDirectRevenue || 0);
        current.adsIndirectRevenue += Number(row.adsIndirectRevenue || 0);
        current.investment += Number(row.investment || 0);
        current.tacosBaseRevenue += Number(row.tacosBaseRevenue || row.revenue || 0);
        current.impressions += Number(row.impressions || 0);
        current.clicks += Number(row.clicks || 0);
        current.adsUnits += Number(row.adsUnits || 0);
        if (Number(row.lastSalePrice || 0) > 0) current.priceFallback = Number(row.lastSalePrice);
        byDate.set(date, current);
      }}));
      const rows = [...byDate.values()]
        .map(row => ({{
          ...row,
          price:row.units > 0 ? row.revenue / row.units : row.priceFallback,
          roas:row.investment > 0 ? row.adsRevenue / row.investment : 0,
          tacos:row.tacosBaseRevenue > 0 ? row.investment / row.tacosBaseRevenue : 0,
        }}))
        .sort((a,b) => a.date.localeCompare(b.date));
      const period = DATA.meta?.onlineMode?.onlinePeriod || DATA.meta?.period || DATA.onlineBeta?.requestedPeriod || {{}};
      const dateFrom = String(period.dateFrom || period.date_from || '');
      const dateTo = String(period.dateTo || period.date_to || '');
      if (!/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(dateFrom) || !/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(dateTo)) return rows;
      const indexed = new Map(rows.map(row => [row.date, row]));
      const complete = [];
      const cursor = new Date(`${{dateFrom}}T12:00:00`);
      const end = new Date(`${{dateTo}}T12:00:00`);
      while (cursor <= end) {{
        const date = cursor.toISOString().slice(0, 10);
        complete.push(indexed.get(date) || {{date, orders:0, units:0, revenue:0, adsRevenue:0, adsDirectRevenue:0, adsIndirectRevenue:0, investment:0, tacosBaseRevenue:0, impressions:0, clicks:0, adsUnits:0, roas:0, tacos:0, price:0, priceFallback:0}});
        cursor.setDate(cursor.getDate() + 1);
      }}
      return complete;
    }}
    function chartDateLabel(value) {{
      const parsed = new Date(`${{value}}T12:00:00`);
      if (Number.isNaN(parsed.getTime())) return value;
      return new Intl.DateTimeFormat('pt-BR', {{day:'numeric', month:'short'}}).format(parsed).replace(/\\s+de\\s+/g, ' ');
    }}
    function chartLongDate(value) {{
      const parsed = new Date(`${{value}}T12:00:00`);
      if (Number.isNaN(parsed.getTime())) return value;
      return new Intl.DateTimeFormat('pt-BR', {{weekday:'short', day:'2-digit', month:'short', year:'numeric'}}).format(parsed);
    }}
    function chartMetricConfig(metric) {{
      const configs = {{
        revenue:{{label:'Faturamento bruto', color:'#7f56d9', format:brl}},
        adsRevenue:{{label:'Receita atribuida Ads', color:'#175cd3', format:brl}},
        investment:{{label:'Investimento Ads', color:'#d92d20', format:brl}},
        roas:{{label:'ROAS realizado', color:'#039855', format:value => `${{Number(value || 0).toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}})}}x`}},
        tacos:{{label:'TACOS realizado', color:'#dc6803', format:value => pct(Number(value || 0))}},
        units:{{label:'Unidades vendidas', color:'#1570ef', format:value => num(value)}},
        orders:{{label:'Pedidos', color:'#12b76a', format:value => num(value)}},
        price:{{label:'Preco medio vendido', color:'#f79009', format:brl}},
      }};
      return configs[metric] || configs.revenue;
    }}
    function campaignConfigFor(item) {{
      const sources = (item.children && item.children.length) ? item.children : [item];
      const configs = new Map();
      sources.forEach(source => {{
        const id = String(source.campaignId || '');
        const budget = source.campaignBudget == null ? null : Number(source.campaignBudget);
        const target = source.campaignTargetRoas == null ? null : Number(source.campaignTargetRoas);
        if (!id || (budget == null && target == null)) return;
        configs.set(`${{id}}|${{budget}}|${{target}}`, {{id, budget, target}});
      }});
      const values = [...configs.values()];
      if (!values.length) return {{count:0, budget:null, target:null}};
      if (values.length > 1) return {{count:values.length, budget:null, target:null}};
      return {{count:1, ...values[0]}};
    }}
    function campaignConfigInline(item) {{
      const config = campaignConfigFor(item);
      if (config.count > 1) return `<div class="campaign-config-inline">${{config.count}} configuracoes de campanha</div>`;
      if (!config.count) return '';
      const parts = [];
      if (config.target != null) parts.push(`Meta ${{config.target.toLocaleString('pt-BR', {{maximumFractionDigits:2}})}}x`);
      if (config.budget != null) parts.push(`Orcamento medio diario ${{brl(config.budget)}}`);
      return parts.length ? `<div class="campaign-config-inline">${{safe(parts.join(' · '))}}</div>` : '';
    }}
    function smoothChartPath(points) {{
      if (!points.length) return '';
      if (points.length === 1) return `M ${{points[0][0]}} ${{points[0][1]}}`;
      let path = `M ${{points[0][0]}} ${{points[0][1]}}`;
      for (let index = 0; index < points.length - 1; index += 1) {{
        const p0 = points[Math.max(0, index - 1)];
        const p1 = points[index];
        const p2 = points[index + 1];
        const p3 = points[Math.min(points.length - 1, index + 2)];
        const c1x = p1[0] + (p2[0] - p0[0]) / 6;
        const c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6;
        const c2y = p2[1] - (p3[1] - p1[1]) / 6;
        path += ` C ${{c1x.toFixed(1)}} ${{c1y.toFixed(1)}}, ${{c2x.toFixed(1)}} ${{c2y.toFixed(1)}}, ${{p2[0].toFixed(1)}} ${{p2[1].toFixed(1)}}`;
      }}
      return path;
    }}
    function movingAverage(values) {{
      return values.map((value, index) => {{
        const start = Math.max(0, index - 1);
        const end = Math.min(values.length - 1, index + 1);
        const slice = values.slice(start, end + 1);
        return slice.reduce((total, current) => total + current, 0) / slice.length;
      }});
    }}
    function chartScale(values, metric) {{
      if (metric === 'tacos') return {{min:0, max:.15}};
      const finite = values.filter(value => Number.isFinite(value));
      if (!finite.length) return {{min:0, max:1}};
      const rawMin = Math.min(...finite);
      const rawMax = Math.max(...finite);
      if (metric !== 'price') return {{min:0, max:Math.max(1, rawMax * 1.12)}};
      if (rawMax === rawMin) {{
        const padding = Math.max(1, rawMax * .06);
        return {{min:Math.max(0, rawMin - padding), max:rawMax + padding}};
      }}
      const padding = (rawMax - rawMin) * .18;
      return {{min:Math.max(0, rawMin - padding), max:rawMax + padding}};
    }}
    function renderDailyMetric(root, metric) {{
      const sourceRows = JSON.parse(decodeURIComponent(root.dataset.chartSeries || '%5B%5D'));
      const rows = metric === 'price' ? sourceRows.filter(row => Number(row.price || 0) > 0) : sourceRows;
      const config = chartMetricConfig(metric);
      const values = rows.map(row => Number(row[metric] || 0));
      const totals = rows.reduce((sum, row) => ({{
        adsRevenue:sum.adsRevenue + Number(row.adsRevenue || 0),
        investment:sum.investment + Number(row.investment || 0),
        tacosBaseRevenue:sum.tacosBaseRevenue + Number(row.tacosBaseRevenue || 0),
      }}), {{adsRevenue:0, investment:0, tacosBaseRevenue:0}});
      const arithmeticAverage = values.reduce((total, value) => total + value, 0) / Math.max(values.length, 1);
      const average = metric === 'roas'
        ? (totals.investment > 0 ? totals.adsRevenue / totals.investment : 0)
        : metric === 'tacos'
          ? (totals.tacosBaseRevenue > 0 ? totals.investment / totals.tacosBaseRevenue : 0)
          : arithmeticAverage;
      const reference = metric === 'roas'
        ? Number(root.dataset.targetRoas || 0)
        : metric === 'investment'
          ? Number(root.dataset.campaignBudget || 0)
          : 0;
      const canvas = root.querySelector('.chart-canvas');
      root.dataset.activeMetric = metric;
      root.querySelectorAll('[data-chart-metric]').forEach(button => button.classList.toggle('active', button.dataset.chartMetric === metric));
      const summaryLabel = ['roas', 'tacos'].includes(metric) ? 'Resultado do periodo' : 'Media do periodo';
      root.querySelector('.chart-summary').textContent = `${{config.label}} por dia. ${{summaryLabel}}: ${{config.format(average)}}.`;
      if (!rows.length || (metric === 'price' && !values.some(value => value > 0))) {{
        canvas.innerHTML = '<div class="muted" style="padding:28px">O snapshot ainda nao possui preco diario suficiente para esta visualizacao.</div>';
        return;
      }}
      const width = 1040, height = metric === 'tacos' ? 360 : 300, left = 76, right = 28, top = 48, bottom = 52;
      const chartW = width - left - right, chartH = height - top - bottom;
      const scale = chartScale(reference > 0 ? [...values, reference] : values, metric);
      const range = Math.max(.0001, scale.max - scale.min);
      const step = chartW / Math.max(rows.length, 1);
      const x = index => left + step * index + step / 2;
      const plottedValue = value => metric === 'tacos'
        ? Math.min(scale.max, Math.max(scale.min, Number(value)))
        : Number(value);
      const y = value => top + chartH - ((plottedValue(value) - scale.min) / range * chartH);
      const ticks = metric === 'tacos'
        ? Array.from({{length:16}}, (_, index) => index / 100)
        : Array.from({{length:5}}, (_, index) => scale.min + ((scale.max - scale.min) * index / 4));
      const grid = ticks.map(value => `<g><line class="chart-grid" x1="${{left}}" y1="${{y(value).toFixed(1)}}" x2="${{width-right}}" y2="${{y(value).toFixed(1)}}"/><text class="chart-axis" x="${{left-12}}" y="${{(y(value)+4).toFixed(1)}}" text-anchor="end">${{safe(config.format(value))}}</text></g>`).join('');
      const averageY = y(average).toFixed(1);
      const averageLine = `<line class="chart-average-line" x1="${{left}}" y1="${{averageY}}" x2="${{width-right}}" y2="${{averageY}}"/><text class="chart-average-label" x="${{width-right-4}}" y="22" text-anchor="end">${{safe(summaryLabel)}} ${{safe(config.format(average))}}</text>`;
      const referenceY = reference > 0 ? y(reference).toFixed(1) : '';
      const referenceLabel = metric === 'roas' ? 'Meta ROAS' : 'Orcamento medio diario';
      const referenceLine = reference > 0
        ? `<line class="chart-reference-line" x1="${{left}}" y1="${{referenceY}}" x2="${{width-right}}" y2="${{referenceY}}"/><text class="chart-reference-label" x="${{left+4}}" y="22">${{safe(referenceLabel)}} ${{safe(config.format(reference))}}</text>`
        : '';
      const labelEvery = Math.max(1, Math.ceil(rows.length / 9));
      const xLabels = rows.map((row,index) => (index % labelEvery === 0 || index === rows.length - 1) ? `<text class="chart-axis" x="${{x(index).toFixed(1)}}" y="${{height-18}}" text-anchor="middle">${{safe(chartDateLabel(row.date))}}</text>` : '').join('');
      const barWidth = Math.max(8, Math.min(34, step * .62));
      const lineOnly = ['price', 'roas', 'tacos'].includes(metric);
      const bars = lineOnly ? '' : rows.map((row,index) => {{
        const barY = y(values[index]);
        return `<rect class="chart-bar" x="${{(x(index)-barWidth/2).toFixed(1)}}" y="${{barY.toFixed(1)}}" width="${{barWidth.toFixed(1)}}" height="${{Math.max(0, top+chartH-barY).toFixed(1)}}" rx="${{Math.min(7,barWidth/3).toFixed(1)}}" fill="${{config.color}}" fill-opacity=".46"/>`;
      }}).join('');
      const trendValues = lineOnly ? values : movingAverage(values);
      const points = trendValues.map((value,index) => [x(index), y(value)]);
      const path = smoothChartPath(points);
      const area = lineOnly && path ? `${{path}} L ${{x(rows.length-1).toFixed(1)}} ${{(top+chartH).toFixed(1)}} L ${{x(0).toFixed(1)}} ${{(top+chartH).toFixed(1)}} Z` : '';
      const dots = lineOnly ? points.map(point => `<circle cx="${{point[0].toFixed(1)}}" cy="${{point[1].toFixed(1)}}" r="4" fill="#fff" stroke="${{config.color}}" stroke-width="2"/>`).join('') : '';
      const extremes = metric === 'tacos' ? rows.map((row,index) => {{
        const actual = Number(row.tacos || 0);
        if (actual <= scale.max) return '';
        const pointX = x(index).toFixed(1);
        return `<g><path class="chart-extreme-marker" d="M ${{pointX}} ${{top-2}} l -6 -9 h 12 Z"/><text class="chart-extreme-label" x="${{pointX}}" y="${{top-16}}" text-anchor="middle">${{safe(config.format(actual))}}</text></g>`;
      }}).join('') : '';
      const hitWidth = Math.max(12, step);
      const hits = rows.map((row,index) => `<g><rect class="chart-hit" data-chart-index="${{index}}" x="${{(x(index)-hitWidth/2).toFixed(1)}}" y="${{top}}" width="${{hitWidth.toFixed(1)}}" height="${{chartH}}"/><line class="chart-hover-line" x1="${{x(index).toFixed(1)}}" y1="${{top}}" x2="${{x(index).toFixed(1)}}" y2="${{top+chartH}}"/></g>`).join('');
      canvas.innerHTML = `<svg class="daily-chart" viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{safe(config.label)}} por dia">
        ${{grid}}${{averageLine}}${{referenceLine}}${{area ? `<path d="${{area}}" fill="${{config.color}}" fill-opacity=".10"/>` : ''}}${{bars}}<path d="${{path}}" fill="none" stroke="${{config.color}}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>${{dots}}${{extremes}}${{hits}}${{xLabels}}
      </svg>`;
      const tooltip = root.querySelector('.chart-tooltip');
      root.querySelectorAll('[data-chart-index]').forEach(hit => {{
        hit.addEventListener('pointerenter', () => showDailyTooltip(root, tooltip, rows[Number(hit.dataset.chartIndex)], metric, hit));
        hit.addEventListener('pointermove', () => showDailyTooltip(root, tooltip, rows[Number(hit.dataset.chartIndex)], metric, hit));
        hit.addEventListener('pointerleave', () => tooltip.classList.remove('visible'));
      }});
    }}
    function showDailyTooltip(root, tooltip, row, metric, hit) {{
      const stage = root.querySelector('.chart-stage');
      const stageRect = stage.getBoundingClientRect();
      const hitRect = hit.getBoundingClientRect();
      const priceText = Number(row.price || 0) > 0 ? brl(Number(row.price)) : 'Sem venda';
      tooltip.innerHTML = `<b>${{safe(chartLongDate(row.date))}}</b>
        <div class="chart-tooltip-row ${{metric === 'revenue' ? 'active' : ''}}"><span>Faturamento</span><span>${{safe(brl(Number(row.revenue || 0)))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'adsRevenue' ? 'active' : ''}}"><span>Receita Ads</span><span>${{safe(brl(Number(row.adsRevenue || 0)))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'investment' ? 'active' : ''}}"><span>Investimento Ads</span><span>${{safe(brl(Number(row.investment || 0)))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'roas' ? 'active' : ''}}"><span>ROAS realizado</span><span>${{safe(chartMetricConfig('roas').format(Number(row.roas || 0)))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'tacos' ? 'active' : ''}}"><span>TACOS realizado</span><span>${{safe(chartMetricConfig('tacos').format(Number(row.tacos || 0)))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'units' ? 'active' : ''}}"><span>Unidades</span><span>${{num(Number(row.units || 0))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'orders' ? 'active' : ''}}"><span>Pedidos</span><span>${{num(Number(row.orders || 0))}}</span></div>
        <div class="chart-tooltip-row ${{metric === 'price' ? 'active' : ''}}"><span>Preco medio</span><span>${{safe(priceText)}}</span></div>`;
      const relativeX = hitRect.left - stageRect.left + hitRect.width / 2;
      tooltip.classList.add('visible');
      const halfWidth = tooltip.getBoundingClientRect().width / 2;
      tooltip.style.left = `${{Math.max(halfWidth + 8, Math.min(stageRect.width - halfWidth - 8, relativeX))}}px`;
      tooltip.style.top = '10px';
    }}
    function activateDailyCharts() {{
      document.querySelectorAll('[data-daily-chart]').forEach(root => {{
        const key = root.dataset.chartKey || '';
        const metric = dailyChartMetric.get(key) || 'revenue';
        root.querySelectorAll('[data-chart-metric]').forEach(button => button.addEventListener('click', () => {{
          dailyChartMetric.set(key, button.dataset.chartMetric);
          renderDailyMetric(root, button.dataset.chartMetric);
        }}));
        renderDailyMetric(root, metric);
      }});
    }}
    function dailyChartBlock(item) {{
      const rows = dailySeriesFor(item);
      if (!rows.length) return `<div class="detail-block detail-block-wide"><h3>Vendas diarias do periodo</h3><div class="muted">A serie diaria ainda nao foi entregue pelo snapshot desta conta. Nenhum zero foi inventado.</div></div>`;
      const key = detailKey(item);
      const encoded = encodeURIComponent(JSON.stringify(rows));
      const campaignConfig = campaignConfigFor(item);
      const configText = value => value == null ? 'Nao informado' : value;
      const budgetText = campaignConfig.count > 1 ? `${{campaignConfig.count}} configuracoes de campanha` : configText(campaignConfig.budget == null ? null : brl(campaignConfig.budget));
      const targetText = campaignConfig.count > 1 ? `${{campaignConfig.count}} configuracoes de campanha` : configText(campaignConfig.target == null ? null : `${{campaignConfig.target.toLocaleString('pt-BR', {{maximumFractionDigits:2}})}}x`);
      const realizedRoas = Number(item.roas || 0).toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}}) + 'x';
      const realizedTacos = pct(Number(item.tacos || 0));
      const targetData = campaignConfig.count === 1 && campaignConfig.target != null ? campaignConfig.target : '';
      const budgetData = campaignConfig.count === 1 && campaignConfig.budget != null ? campaignConfig.budget : '';
      return `<div class="detail-block detail-block-wide daily-chart-card" data-daily-chart data-chart-key="${{safe(key)}}" data-chart-series="${{safe(encoded)}}" data-target-roas="${{safe(targetData)}}" data-campaign-budget="${{safe(budgetData)}}"><div class="campaign-config-grid"><div class="campaign-config-card"><span>Orcamento medio diario</span><b>${{safe(budgetText)}}</b></div><div class="campaign-config-card"><span>ROAS objetivo</span><b>${{safe(targetText)}}</b></div><div class="campaign-config-card"><span>ROAS realizado</span><b>${{safe(realizedRoas)}}</b></div><div class="campaign-config-card"><span>TACOS realizado</span><b>${{safe(realizedTacos)}}</b></div></div><div class="chart-head"><div><h3>Desempenho diario do produto</h3><div class="chart-summary">Selecione uma metrica para visualizar.</div></div><div class="chart-metric-tabs" role="group" aria-label="Metrica do grafico"><button class="chart-metric-button" type="button" data-chart-metric="revenue">Faturamento</button><button class="chart-metric-button" type="button" data-chart-metric="adsRevenue">Receita Ads</button><button class="chart-metric-button" type="button" data-chart-metric="investment">Investimento</button><button class="chart-metric-button" type="button" data-chart-metric="roas">ROAS</button><button class="chart-metric-button" type="button" data-chart-metric="tacos">TACOS</button><button class="chart-metric-button" type="button" data-chart-metric="units">Unidades</button><button class="chart-metric-button" type="button" data-chart-metric="orders">Pedidos</button><button class="chart-metric-button" type="button" data-chart-metric="price">Preco medio</button></div></div><div class="chart-stage"><div class="chart-canvas"></div><div class="chart-tooltip"></div></div></div>`;
    }}
    function shippingBadgeText(item) {{
      const price = Number(item.currentPrice || item.lastPrice || 0);
      if (item.freeShipping === true) {{
        if (price > 0 && price < 79) {{
          if (item.fastShipping === true) return 'Frete gratis e rapido';
          if (item.fastShipping === false) return 'Frete gratis';
          return 'Frete gratis; rapidez nao informada';
        }}
        return price >= 79 ? 'Frete gratis obrigatorio' : 'Frete gratis';
      }}
      if (item.freeShipping === false) return 'Frete por conta do comprador';
      return 'Frete nao informado';
    }}
    function listingBadges(item) {{
      const listing = listingTypeLabel(item.listingTypeId);
      const shipping = shippingBadgeText(item);
      const listingClass = listing === 'Premium' ? 'premium' : listing === 'Classico' ? 'classic' : '';
      const shippingClass = item.freeShipping === true ? 'shipping-on' : item.freeShipping === false ? 'shipping-off' : '';
      return `<div class="listing-badges"><span class="listing-mini-badge ${{listingClass}}">${{safe(listing)}}</span><span class="listing-mini-badge ${{shippingClass}}">${{safe(shipping)}}</span></div>`;
    }}
    function listingFactsBlock(item) {{
      const freeShipping = shippingBadgeText(item);
      const shippingCost = Number(item.shippingCost || 0) > 0 ? brl(item.shippingCost) : 'Nao fornecido pelo cache';
      return `<div class="detail-block detail-block-wide"><h3>Condicao comercial do anuncio</h3><div class="listing-facts">
        <div class="listing-fact"><span class="muted">Classificacao</span><b>${{safe(listingTypeLabel(item.listingTypeId))}}</b></div>
        <div class="listing-fact"><span class="muted">Logistica</span><b>${{safe(logisticLabel(item.logisticType))}}</b></div>
        <div class="listing-fact"><span class="muted">Frete gratis</span><b>${{safe(freeShipping)}}</b></div>
        <div class="listing-fact"><span class="muted">Custo estimado do frete</span><b>${{safe(shippingCost)}}</b></div>
        <div class="listing-fact"><span class="muted">Preco do anuncio no snapshot</span><b>${{item.currentPrice ? brl(item.currentPrice) : 'Nao informado'}}</b></div>
        <div class="listing-fact"><span class="muted">Preco da ultima venda</span><b>${{item.lastSalePrice ? brl(item.lastSalePrice) : 'Nao informado'}}</b></div>
        <div class="listing-fact"><span class="muted">Preco medio vendido</span><b>${{item.avgSalePrice ? brl(item.avgSalePrice) : 'Sem venda no periodo'}}</b></div>
        <div class="listing-fact"><span class="muted">Ultima venda</span><b>${{item.lastSaleDate ? safe(formatLastSaleDate(item.lastSaleDate)) : 'Nao informada'}}</b></div>
      </div></div>`;
    }}
    function pricingPreviewBlock(item) {{
      const change = Number(item.priceChangePct || 0);
      const hasSignal = item.pricingSignal === 'indicio_alta_preco_com_interrupcao' && Number(item.suggestedTestPrice || 0) > 0;
      const analysis = hasSignal
        ? `O preco observado esta ${{(change * 100).toLocaleString('pt-BR', {{minimumFractionDigits:1, maximumFractionDigits:1}})}}% acima da ultima venda. Isso e um indicio, nao prova de causalidade.`
        : 'Ainda nao ha evidencia suficiente no cache para atribuir a variacao de vendas ao preco.';
      const suggestion = hasSignal
        ? `Teste sugerido: ${{brl(item.suggestedTestPrice)}}. O valor preserva 60% do aumento observado e deve ser validado com margem, tarifa e frete.`
        : 'Nenhum preco de teste foi calculado.';
      return `<div class="detail-block detail-block-wide price-signal"><span class="readonly-badge">PREVIA SOMENTE LEITURA</span><h3>Hipotese de preco e promocao</h3><p>${{safe(analysis)}}</p><p><b>${{safe(suggestion)}}</b></p><div class="muted">Elegibilidade de promocao: nao consultada pelo cache atual. Esta etapa nao cria promocao, nao altera preco e nao envia comandos ao Mercado Livre.</div></div>`;
    }}
    function detailBlocks(item) {{
      const evidence = [
        `Confianca: ${{item.confidence || 'hipotese'}}`,
        ...((item.confidenceReasons || []).map(value => `Evidencia: ${{value}}`)),
        ...((item.validationPoints || []).map(value => `Validar: ${{value}}`))
      ];
      if (item.campaignRevenueAmbiguous) evidence.unshift('TACOS da campanha e orientativo: o mesmo MLB aparece em mais de uma campanha.');
      return dailyChartBlock(item)
        + listingFactsBlock(item)
        + pricingPreviewBlock(item)
        + listBlock('Leitura e confianca', evidence)
        + listBlock('Causas mais provaveis', item.diagnosisHypotheses)
        + listBlock('O que fazer agora', item.testOrder)
        + campaignChildren(item);
    }}
    function productParentSummary(children) {{
      const sum = key => children.reduce((total, item) => total + Number(item[key] || 0), 0);
      const totalRevenue = sum('totalRevenue');
      const units = sum('units');
      const investment = sum('investment');
      const adsRevenue = sum('adsRevenue');
      const impressions = sum('impressions');
      const clicks = sum('clicks');
      const adsSales = sum('adsSales');
      const tacosBaseRevenue = children.reduce(
        (total, item) => total + Number(item.tacosBaseRevenue ?? item.totalRevenue ?? 0), 0
      );
      const latest = children.reduce((current, item) => {{
        if (!item.lastSaleDate) return current;
        if (!current) return item;
        const itemTime = Date.parse(item.lastSaleDate);
        const currentTime = Date.parse(current.lastSaleDate);
        if (Number.isNaN(itemTime)) return current;
        if (Number.isNaN(currentTime)) return item;
        return itemTime > currentTime ? item : current;
      }}, null);
      const campaigns = new Set(children.map(item => item.campaign || item.adsCampaigns).filter(Boolean));
      const catalogs = new Set(children.map(item => item.catalogProductId).filter(Boolean));
      const skus = new Set(children.map(item => item.sku).filter(Boolean));
      const picturedChildren = children.filter(item => imageUrl(item.thumbnailUrl));
      const thumbnailSource = [...picturedChildren].sort((a, b) => (b.totalRevenue || 0) - (a.totalRevenue || 0))[0];
      const cvr = clicks ? adsSales / clicks : 0;
      const avgAdsOrder = adsSales ? adsRevenue / adsSales : (units ? totalRevenue / units : 0);
      return {{
        children,
        parentId: children[0].userProductId,
        sku: skus.size === 1 ? [...skus][0] : `${{skus.size}} SKUs`,
        optionCount: children.length,
        campaignCount: campaigns.size,
        catalogLabel: [...catalogs].join(', '),
        thumbnailUrl: thumbnailSource ? thumbnailSource.thumbnailUrl : '',
        thumbnailCount: picturedChildren.length,
        orders: sum('orders'), units, totalRevenue, adsRevenue, investment, impressions, clicks, adsSales,
        lastSaleDate: latest ? latest.lastSaleDate : '',
        lastPrice: latest ? Number(latest.lastPrice || 0) : 0,
        avgSalePrice: units ? totalRevenue / units : 0,
        cpc: clicks ? investment / clicks : 0,
        ctr: impressions ? clicks / impressions : 0,
        cvr,
        tacos: tacosBaseRevenue ? investment / tacosBaseRevenue : 0,
        roas: investment ? adsRevenue / investment : 0,
        maxCpc: avgAdsOrder && cvr ? avgAdsOrder * .03 * cvr : 0
      }};
    }}
    function imageUrl(value) {{
      if (!value) return '';
      try {{
        const parsed = new URL(String(value), window.location.href);
        if (parsed.protocol === 'http:') parsed.protocol = 'https:';
        return parsed.protocol === 'https:' ? parsed.href : '';
      }} catch (error) {{
        return '';
      }}
    }}
    function productImage(item) {{
      const url = imageUrl(item.thumbnailUrl);
      const count = Math.max(0, Number(item.thumbnailCount || 0));
      const badge = count > 1 ? `<span class="product-thumbnail-count">+${{count - 1}}</span>` : '';
      if (!url) return `<div class="product-thumbnail" aria-label="Imagem indisponivel">SEM<br>FOTO</div>`;
      return `<div class="product-thumbnail"><img src="${{safe(url)}}" alt="${{safe(item.title || item.sku || 'Produto')}}" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.parentElement.textContent='SEM FOTO'">${{badge}}</div>`;
    }}
    function productParentRow(item) {{
      return `<tr class="product-parent-row">
        <td>${{productImage(item)}}</td>
        <td><span class="code">${{safe(item.sku || '(sem SKU)')}}</span><div class="muted">Produto pai</div></td>
        <td class="text-cell"><div class="copyline"><span class="code">${{safe(item.parentId)}}</span>${{copyButton(item.parentId, 'MLBU')}}</div><div class="title">Resumo consolidado de ${{num(item.optionCount)}} opcoes</div></td>
        <td><span class="summary-chip">PAI</span></td>
        <td class="text-cell">${{num(item.campaignCount)}} campanha(s) Ads<div class="muted">campanhas individuais preservadas</div>${{campaignConfigInline(item)}}</td>
        <td class="text-cell">${{safe(item.parentId)}} · ${{num(item.optionCount)}} opcao(oes)<div class="muted">${{safe(item.catalogLabel)}}</div></td>
        <td class="num">${{(item.currentPrice || item.lastPrice) ? brl(item.currentPrice || item.lastPrice) : '-'}}<div class="muted">${{item.lastSalePrice ? 'ultima venda: ' + brl(item.lastSalePrice) : ''}}</div><div class="muted">${{item.avgSalePrice ? 'media vendida: ' + brl(item.avgSalePrice) : ''}}</div><div class="muted">${{item.lastSaleDate ? safe(formatLastSaleDate(item.lastSaleDate)) : ''}}</div></td>
        <td class="num">${{num(item.orders || 0)}}</td><td class="num">${{num(item.units || 0)}}</td><td class="num">${{brl(item.totalRevenue || 0)}}</td><td class="num">${{brl(item.adsRevenue || 0)}}</td><td class="num">${{brl(item.investment || 0)}}</td>
        <td class="num">${{brl(item.cpc || 0)}}<div class="muted">max ${{brl(item.maxCpc || 0)}}</div></td><td class="num">${{pct(item.ctr || 0)}}</td><td class="num">${{pct(item.cvr || 0)}}</td><td class="num">${{pct(item.tacos || 0)}}</td><td class="num">${{(item.roas || 0).toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}})}}</td>
      </tr>`;
    }}
    function productGroupNote(optionCount) {{
      return `<tr class="product-group-note"><td colspan="17"><b>Mesmo produto:</b> pai e ${{num(optionCount)}} condicao(oes) de venda no mesmo quadro. Valores do pai sao consolidados e as taxas sao recalculadas sobre os totais.</td></tr>`;
    }}
    function splitByMlbu(rows) {{
      const groups = new Map();
      rows.forEach((item, index) => {{
        const parentId = item.userProductId || '';
        const key = parentId ? `parent:${{parentId}}` : `item:${{item.code || index}}`;
        if (!groups.has(key)) groups.set(key, {{ parentId, children:[] }});
        groups.get(key).children.push(item);
      }});
      return [...groups.values()];
    }}
    function mlbuGroupBody(group) {{
      if (group.parentId && group.children.length > 1) {{
        return `<tbody class="product-group">${{productParentRow(productParentSummary(group.children))}}${{group.children.map(item => row(item, 'product-child-row')).join('')}}${{productGroupNote(group.children.length)}}</tbody>`;
      }}
      return `<tbody>${{group.children.map(item => row(item)).join('')}}</tbody>`;
    }}
    function groupedMlbBodies(rows) {{
      return splitByMlbu(rows).map(mlbuGroupBody).join('');
    }}
    function groupedSkuBodies(rows) {{
      return rows.map(sku => splitByMlbu(sku.children || []).map(mlbuGroupBody).join('') || `<tbody>${{row(sku)}}</tbody>`).join('');
    }}
    function row(item, extraClass = '') {{
      const key = detailKey(item);
      const expanded = detailExpanded.has(key);
      const campaignMode = currentViewMode === 'campaign';
      const abcValue = campaignMode ? item.abcCampaign : currentViewMode === 'sku' ? item.abcSku : item.abcCode;
      const tacosNote = item.salesCoverageComplete === false ? 'vendas parciais' : item.campaignRevenueAmbiguous ? 'atribuicao ambigua' : '';
      return `<tr class="main-row ${{extraClass}}">
        <td>${{productImage(item)}}</td>
        <td><div class="copyline"><span class="code">${{safe(item.sku || '(sem SKU)')}}</span>${{copyButton(item.sku, 'SKU')}}</div><div class="muted">${{item.adCount ? item.adCount + ' anuncios' : ''}}</div>${{campaignMode ? '' : listingBadges(item)}}</td>
        <td class="text-cell"><div class="copyline"><span class="code">${{safe(item.allCodes || item.code || '')}}</span>${{copyButton(item.allCodes || item.code, 'MLB')}}</div><div class="title">${{safe(campaignMode ? (item.topInvestmentLabel || item.title || '') : (item.title || ''))}}</div></td>
        <td><span class="${{abcClass(abcValue)}}">${{campaignMode ? 'CAMP' : currentViewMode.toUpperCase()}} ${{abcValue || 'C'}}</span></td>
        <td class="text-cell">${{safe(item.campaign || item.adsCampaigns || 'Sem campanha')}}<div class="muted">${{safe(item.campaignStatus || '')}}</div>${{campaignMode ? '' : campaignConfigInline(item)}}</td>
        <td class="text-cell">${{safe(item.conditionLabel || 'Sem vinculo MLBU')}}<div class="muted">${{safe(item.catalogLabel || '')}}</div></td>
        <td class="num">${{(item.currentPrice || item.lastPrice) ? brl(item.currentPrice || item.lastPrice) : '-'}}<div class="muted">${{item.lastSalePrice ? 'ultima venda: ' + brl(item.lastSalePrice) : ''}}</div><div class="muted">${{item.avgSalePrice ? 'media vendida: ' + brl(item.avgSalePrice) : ''}}</div><div class="muted">${{item.lastSaleDate ? safe(formatLastSaleDate(item.lastSaleDate)) : ''}}</div></td>
        <td class="num">${{num(item.orders || 0)}}</td><td class="num">${{num(item.units || 0)}}</td><td class="num">${{brl(item.totalRevenue || 0)}}</td><td class="num">${{brl(item.adsRevenue || 0)}}</td><td class="num">${{brl(item.investment || 0)}}</td>
        <td class="num">${{brl(item.cpc || 0)}}<div class="muted">max ${{brl(item.maxCpc || 0)}}</div></td>
        <td class="num">${{pct(item.ctr || 0)}}<div class="muted">${{safe(item.ctrClass || '')}}</div></td><td class="num">${{pct(item.cvr || 0)}}<div class="muted">${{safe(item.cvrClass || '')}}</div></td>
        <td class="num">${{pct(item.tacos || 0)}}<div class="muted">${{safe(tacosNote)}}</div></td><td class="num">${{(item.roas || 0).toLocaleString('pt-BR', {{minimumFractionDigits:2, maximumFractionDigits:2}})}}</td>
      </tr>
      <tr class="decision-row"><td colspan="17"><div class="decision-wrap">
        <div class="decision-summary-main"><span class="pill ${{actionClass(item.action)}}">${{safe(item.action)}}</span><div class="decision-teaser"><b>Diagnostico:</b> ${{safe(item.diagnosticSummary || item.recommendation || item.reason || 'Sem leitura adicional.')}}</div></div>
        <div class="decision-summary-side"><span class="summary-chip">${{safe(item.adsDependencyLabel || 'Dependencia nao calculada')}}</span><span class="summary-chip">Alerta principal: ${{safe((item.alerts || [])[0] || 'Sem alerta')}}</span><button class="secondary-action detail-toggle" type="button" data-detail-toggle="${{safe(key)}}">${{expanded ? 'Ocultar leitura' : 'Ver leitura'}}</button></div>
      </div></td></tr>
      <tr class="detail-row" style="display:${{expanded ? 'table-row' : 'none'}}"><td colspan="17"><div class="detail-grid">${{detailBlocks(item)}}</div></td></tr>`;
    }}
    function renderTable() {{
      renderAlerts();
      const q = document.getElementById('search').value.toLowerCase();
      let rows = rowsByViewMode().filter(item => matchesContext(item) && itemSearchText(item).includes(q));
      if (sortState.key && sortState.direction !== 0) {{
        const getter = sortKeys[sortState.key];
        rows = [...rows].sort((a,b) => {{
          const av = getter(a); const bv = getter(b);
          if (typeof av === 'number' || typeof bv === 'number') return sortState.direction === 1 ? (bv - av) : (av - bv);
          return sortState.direction === 1 ? String(bv).localeCompare(String(av), 'pt-BR') : String(av).localeCompare(String(bv), 'pt-BR');
        }});
      }}
      document.getElementById('tableTitle').textContent = `${{contextLabels[currentContext]}} - ${{viewLabels[currentViewMode]}} (${{rows.length}})`;
      const renderedBodies = currentViewMode === 'mlb'
        ? groupedMlbBodies(rows)
        : currentViewMode === 'sku'
          ? groupedSkuBodies(rows)
          : `<tbody>${{rows.map(item => row(item)).join('')}}</tbody>`;
      document.getElementById('table').innerHTML = `<table class="ops-table">
        <colgroup><col style="width:72px"><col style="width:110px"><col style="width:300px"><col style="width:86px"><col style="width:190px"><col style="width:190px"><col style="width:120px"><col style="width:72px"><col style="width:72px"><col style="width:108px"><col style="width:108px"><col style="width:96px"><col style="width:84px"><col style="width:78px"><col style="width:78px"><col style="width:90px"><col style="width:70px"></colgroup>
        <thead><tr><th>Imagem</th><th>${{sortable('SKU','sku')}}</th><th>${{sortable(currentViewMode === 'campaign' ? 'Resumo' : 'Anuncio','code')}}</th><th>ABC</th><th>Campanha Ads</th><th>Condicao/opcao de venda</th><th class="num">${{sortable('Preco','price')}}</th><th class="num">${{sortable('Pedidos','orders')}}</th><th class="num">${{sortable('Unidades','units')}}</th><th class="num">${{sortable('Receita','revenue')}}</th><th class="num">${{sortable('Receita ADS','adsRevenue')}}</th><th class="num">${{sortable('Invest.','investment')}}</th><th class="num">${{sortable('CPC','cpc')}}</th><th class="num">${{sortable('CTR','ctr')}}</th><th class="num">${{sortable('CVR','cvr')}}</th><th class="num">${{sortable('TACOS','tacos')}}</th><th class="num">${{sortable('ROAS','roas')}}</th></tr></thead>
        ${{renderedBodies}}</table>`;
      const helpText = document.getElementById('tableHelpText');
      const helpMeta = document.getElementById('tableHelpMeta');
      if (currentViewMode === 'campaign') {{
        helpText.textContent = 'A visao de campanha preserva o agrupamento e os calculos proprios de cada campanha; o agrupamento visual por produto nao altera esta camada.';
      }} else if (currentViewMode === 'sku') {{
        helpText.textContent = 'A aba SKU mantem cada SKU como contexto. Dentro dele, cada MLBU tem seu proprio quadro com o pai acima das condicoes; outro MLBU ou anuncio tradicional permanece separado.';
      }} else {{
        helpText.textContent = 'Cada MLBU aparece como um quadro: produto pai acima e condicoes de venda abaixo. O pai soma valores absolutos e recalcula TACOS, ROAS, CTR e CVR sobre os totais.';
      }}
      helpMeta.textContent = `${{num(rows.length)}} registro(s) no filtro atual`;
      applyTableZoom();
      activateDailyCharts();
      document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {{
        const value = button.dataset.copy;
        try {{ await navigator.clipboard.writeText(value); }} catch (error) {{ const input = document.createElement('textarea'); input.value = value; document.body.appendChild(input); input.select(); document.execCommand('copy'); input.remove(); }}
      }}));
      document.querySelectorAll('[data-detail-toggle]').forEach(button => button.addEventListener('click', () => {{
        const key = button.dataset.detailToggle;
        if (detailExpanded.has(key)) detailExpanded.delete(key); else detailExpanded.add(key);
        renderTable();
      }}));
      document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {{
        const key = button.dataset.sort;
        if (sortState.key !== key) sortState = {{ key, direction:1 }};
        else if (sortState.direction === 1) sortState = {{ key, direction:-1 }};
        else sortState = {{ key:null, direction:0 }};
        renderTable();
      }}));
    }}
    function renderOnlineBeta() {{
      const beta = DATA.onlineBeta || {{}};
      const summaryNode = document.getElementById('onlineBetaSummary');
      const statusNode = document.getElementById('onlineBetaStatus');
      const periodNode = document.getElementById('onlineBetaPeriod');
      const tableNode = document.getElementById('onlineBetaTable');
      if (!beta.enabled) {{
        summaryNode.innerHTML = '';
        periodNode.textContent = 'Online Beta indisponivel nesta analise.';
        statusNode.textContent = 'Preencha o cliente ML no envio para habilitar a leitura online autenticada.';
        tableNode.innerHTML = '';
        return;
      }}
      const periodMatch = !!beta.periodMatch;
  const requested = beta.requestedPeriod || DATA.meta?.onlineMode?.onlinePeriod || {{}};
  const apiPeriod = beta.apiPeriod || DATA.meta?.period || {{}};
  const periodText = `Solicitado: ${{requested.dateFrom || '-'}} a ${{requested.dateTo || '-'}} | Cache/API: ${{apiPeriod.dateFrom || '-'}} a ${{apiPeriod.dateTo || '-'}}`;
  const snapshot = beta.snapshot || DATA.meta?.onlineMode?.snapshot || {{}};
  const snapshotAgeSeconds = Number(snapshot.snapshotAgeSeconds);
  const snapshotAge = Number.isFinite(snapshotAgeSeconds)
    ? ` (${{Math.max(0, Math.floor(snapshotAgeSeconds / 60))}} min de idade)`
    : '';
  const snapshotText = `Solicitado em: ${{snapshot.requestedAt || '-'}} | Snapshot utilizado: ${{snapshot.snapshotAt || '-'}}${{snapshotAge}}`;
  periodNode.textContent = `${{periodText}} | ${{snapshotText}}`;
      const summary = beta.summary || {{}};
      summaryNode.innerHTML = [
        ['Cliente', beta.client || '-', ''],
        ['Advertiser', beta.advertiserId || '-', ''],
        ['Itens OK', num(summary.matchedItems || 0), 'good'],
        ['Itens divergentes', num((summary.divergentItems || 0) + (summary.missingItems || 0)), (summary.divergentItems || summary.missingItems) ? 'danger' : 'good'],
      ].map(([label, value, cls]) => `<div class="card kpi ${{cls}}"><small>${{label}}</small><strong>${{value}}</strong></div>`).join('');
      const latest = beta.latest || {{}};
      const latestAds = latest.ads || {{}};
      const latestSales = latest.latest?.sales || latest.sales || {{}};
      const warning = requested.warning ? `<span class="status-warn">${{safe(requested.warning)}}</span><br>` : '';
      statusNode.innerHTML = `
        <span class="${{periodMatch ? 'status-ok' : 'status-warn'}}">${{periodMatch ? 'Periodo solicitado aplicado ao cache online.' : 'O cache retornou outro intervalo; leitura deve ser conferida.'}}</span><br>
        ${{warning}}
    Fonte: ${{safe(snapshot.snapshotSource || 'cache online')}} | Frequência prevista: ${{safe(snapshot.snapshotCadence || '-')}}<br>
    Cache online: ${{safe(latest.latest?.updated_at || latest.updated_at || '-')}} | Ads online: ${{num(latestAds.items_total || 0)}} linhas | Vendas online em cache: ${{num(latestSales.items_cached || 0)}} itens.
      `;
      const rows = (beta.items || []).map(item => `
        <tr>
          <td><span class="code">${{safe(item.code)}}</span><div class="muted">${{safe(item.sku || '')}}</div></td>
          <td>${{safe(item.xlsxCampaign || '-')}}<div class="muted">API campanha: ${{safe(item.apiCampaign || '-')}}</div></td>
          <td class="num">${{brl(item.xlsxAdsRevenue || 0)}}<div class="muted">dir ${{brl(item.xlsxDirectRevenue || 0)}} | ind ${{brl(item.xlsxIndirectRevenue || 0)}}</div></td>
          <td class="num">${{brl(item.apiAdsRevenue || 0)}}<div class="muted">dir ${{brl(item.apiDirectRevenue || 0)}} | ind ${{brl(item.apiIndirectRevenue || 0)}}</div></td>
          <td class="num">${{brl(item.xlsxInvestment || 0)}}</td>
          <td class="num">${{brl(item.apiInvestment || 0)}}</td>
          <td class="num">${{num(item.xlsxClicks || 0)}}</td>
          <td class="num">${{num(item.apiClicks || 0)}}</td>
          <td class="num">${{brl(item.revenueDelta || 0)}}</td>
          <td><span class="${{item.status === 'OK' ? 'status-ok' : (item.status === 'Divergente' ? 'status-bad' : 'status-warn')}}">${{safe(item.status)}}</span></td>
        </tr>
      `).join('');
      tableNode.innerHTML = `
        <table class="ops-table">
          <colgroup>
            <col style="width:150px"><col style="width:260px"><col style="width:150px"><col style="width:150px"><col style="width:110px"><col style="width:110px"><col style="width:90px"><col style="width:90px"><col style="width:110px"><col style="width:120px">
          </colgroup>
          <thead><tr>
            <th>MLB</th><th>Campanha</th><th class="num">XLSX receita ADS</th><th class="num">API receita ADS</th><th class="num">XLSX invest.</th><th class="num">API invest.</th><th class="num">XLSX cliques</th><th class="num">API cliques</th><th class="num">Delta receita</th><th>Status</th>
          </tr></thead>
          <tbody>${{rows || '<tr><td colspan="10">Nenhum item reconciliado nesta analise.</td></tr>'}}</tbody>
        </table>
      `;
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
      currentContext = event.target.value;
      sortState = {{ key:'investment', direction:1 }};
      renderTable();
    }});
    document.querySelectorAll('#viewMode button[data-view-mode]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('#viewMode button[data-view-mode]').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        currentViewMode = button.dataset.viewMode;
        detailExpanded.clear();
        sortState = {{ key:'investment', direction:1 }};
        renderTable();
      }});
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
    document.getElementById('tableZoomOut').addEventListener('click', () => stepTableZoom(-1));
    document.getElementById('tableZoomIn').addEventListener('click', () => stepTableZoom(1));
    document.getElementById('tableZoomFit').addEventListener('click', fitTableToWidth);
    document.getElementById('tableZoomReset').addEventListener('click', () => setTableZoom(1));
    document.getElementById('tableTop').addEventListener('click', () => window.scrollTo({{ top:0, behavior:'smooth' }}));
    document.getElementById('search').addEventListener('input', renderTable);
    document.getElementById('abcSearch').addEventListener('input', renderAbc);
    renderKpis(); renderAbc(); renderAlerts(); renderTable(); renderOnlineBeta();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    print("Use abrir_dashboard_ads_ml_corrigido.bat para iniciar o app atualizado em http://127.0.0.1:4182")
