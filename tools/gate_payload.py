"""Roda DENTRO do serviço do dashboard (somente leitura). Mede a página real de cada conta."""
import json, os, sys, time, resource
sys.path.insert(0, "/opt/render/project/src"); os.chdir("/opt/render/project/src")
import app as A
from gerar_dashboard_ads_ml import _compact_dashboard_transport, render_dashboard
from datetime import date, timedelta

from datetime import datetime
from zoneinfo import ZoneInfo
end = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=1)  # mesmo dia do dashboard (Brasília)
cur = (end - timedelta(days=29), end)
prev = (cur[0] - timedelta(days=30), cur[0] - timedelta(days=1))
period = {"dateFrom": cur[0].isoformat(), "dateTo": cur[1].isoformat(), "compareMode": "previous",
          "comparePeriod": {"dateFrom": prev[0].isoformat(), "dateTo": prev[1].isoformat()}}
out = {"period": period, "accounts": {}}
for client in sys.argv[1:]:
    runs = []
    for _ in range(2):
        t = time.time()
        data, err = A._build_online_dashboard_data(client, "", period["dateFrom"], period["dateTo"])
        if not data:
            runs.append({"error": err or "sem_dados", "secs": round(time.time() - t, 1)})
            continue
        data = _compact_dashboard_transport(data)
        A._attach_account_period_comparison(data, client, "", period)
        html = render_dashboard(data)
        m = data["periodComparison"].get("metrics", {})
        runs.append({"secs": round(time.time() - t, 1), "html_mb": round(len(html.encode()) / 1e6, 2),
                     "available": sorted(k for k, v in m.items() if v.get("status") in ("available", "zero_baseline"))})
        del data, html
    out["accounts"][client] = runs
out["rss_peak_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
try:
    out["mem_limit_mb"] = int(open("/sys/fs/cgroup/memory.max").read()) // 1048576
    out["mem_peak_mb"] = int(open("/sys/fs/cgroup/memory.peak").read()) // 1048576
except Exception:
    pass
print("GATE_JSON " + json.dumps(out))
