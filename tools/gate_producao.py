"""Teste de produção obrigatório depois de cada deploy do Dash Ads (dashboard ou agente).

Mede nos serviços reais, só lendo: tempo da página e tamanho do HTML (Passo a Passo = menor,
Lonas = maior), comparações disponíveis, disco livre do agente e memória do dashboard.
Reprova (exit 1) se qualquer limite for ultrapassado ou se uma métrica antes disponível virar N/D.

Uso:  bash tools/gate_producao.sh [--atualizar-base]
Chave SSH: RENDER_SSH_KEY (padrão $LOCALAPPDATA/dashads/ssh/render_diag).
"""
import json, sys
from pathlib import Path

LIMITES = {"pagina_segundos": 20.0, "html_mb": 16.0, "disco_livre_pct_min": 20.0, "memoria_pct_max": 85.0}
BASE = Path(__file__).with_name("gate_baseline.json")


def main():
    # Medições vêm do gate_producao.sh (stdin): linha GATE_JSON do dashboard + linha DISK do agente.
    out = sys.stdin.read()
    line = next((l for l in out.splitlines() if l.startswith("GATE_JSON ")), None)
    disk = next((l for l in out.splitlines() if l.startswith("DISK ")), "DISK -1")
    falhas = []
    if not line:
        print(out[-2000:]); print("REPROVADO: medição do dashboard não retornou"); return 1
    res = json.loads(line[len("GATE_JSON "):])
    livre = int(disk.split()[1])
    mem = next((l for l in out.splitlines() if l.startswith("MEM ")), "MEM").split()[1:]
    if len(mem) == 2:
        res["mem_peak_mb"], res["mem_limit_mb"] = int(mem[0]), int(mem[1])
    base = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {}
    print(f"período {res['period']['dateFrom']}..{res['period']['dateTo']}")
    for conta, runs in res["accounts"].items():
        r = runs[-1]
        if "error" in r:
            falhas.append(f"{conta}: página não montou ({r['error']})"); continue
        print(f"{conta}: 1ª {runs[0].get('secs')} s, 2ª {r['secs']} s, HTML {r['html_mb']} MB, comparações {len(r['available'])}")
        if r["secs"] > LIMITES["pagina_segundos"]:
            falhas.append(f"{conta}: página {r['secs']} s > {LIMITES['pagina_segundos']} s")
        if r["html_mb"] > LIMITES["html_mb"]:
            falhas.append(f"{conta}: HTML {r['html_mb']} MB > {LIMITES['html_mb']} MB")
        perdidas = sorted(set(base.get(conta, {}).get("available", [])) - set(r["available"]))
        if perdidas:
            falhas.append(f"{conta}: comparações que viraram N/D: {', '.join(perdidas)}")
    print(f"disco livre do agente: {livre}%")
    if livre < LIMITES["disco_livre_pct_min"]:
        falhas.append(f"disco do agente com {livre}% livre < {LIMITES['disco_livre_pct_min']}%")
    if res.get("mem_limit_mb") and res.get("mem_peak_mb"):
        pct = 100 * res["mem_peak_mb"] / res["mem_limit_mb"]
        print(f"memória do dashboard: pico {res['mem_peak_mb']}/{res['mem_limit_mb']} MB ({pct:.0f}%)")
        if pct > LIMITES["memoria_pct_max"]:
            falhas.append(f"memória do dashboard em {pct:.0f}% > {LIMITES['memoria_pct_max']}%")
    if falhas:
        print("REPROVADO:"); [print(" -", f) for f in falhas]; return 1
    if "--atualizar-base" in sys.argv:
        BASE.write_text(json.dumps({c: {"available": runs[-1]["available"]} for c, runs in res["accounts"].items()},
                                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("linha de base atualizada")
    print("APROVADO"); return 0


if __name__ == "__main__":
    sys.exit(main())
