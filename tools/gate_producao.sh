#!/usr/bin/env bash
# Teste de produção obrigatório após deploy do Dash Ads (ver tools/gate_producao.py).
# Monta as páginas NESTE computador, lendo o agente de produção por túnel SSH: zero carga no dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."
K="${RENDER_SSH_KEY:-$LOCALAPPDATA/dashads/ssh/render_diag}"
S="${DASH_ADS_SECRET_FILE:-$LOCALAPPDATA/dashads/ssh/internal_secret}"
DASH=srv-d86v0in7f7vs73f3tp5g@ssh.oregon.render.com
AGENT=srv-d88hll6l51nc73fgg8f0@ssh.oregon.render.com
PORT=18080
CONTAS="passoapassoecommerce-1478 conta-ativa"
ssh -i "$K" -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L $PORT:127.0.0.1:10000 "$AGENT" 2>/dev/null &
TUNEL=$!
trap 'kill $TUNEL 2>/dev/null || true' EXIT
for _ in $(seq 1 15); do curl -s -o /dev/null --max-time 3 http://127.0.0.1:$PORT/ && break; sleep 2; done
{
  DASH_ADS_INTERNAL_SECRET="$(cat "$S")" AGENTE_ML_BASE_URL=http://127.0.0.1:$PORT RODAR_SCHEDULER=0     DATA_DIR="$(mktemp -d)" PYTHONIOENCODING=utf-8 python tools/gate_payload.py $CONTAS 2>/dev/null | grep '^GATE_JSON ' || true
  echo "DISK $(ssh -i "$K" -o BatchMode=yes "$AGENT" "df -P /var/data | tail -1" 2>/dev/null | awk '{gsub("%","",$5); print 100-$5}')"
  echo "MEM $(ssh -i "$K" -o BatchMode=yes "$DASH" "echo \$(( \$(cat /sys/fs/cgroup/memory.peak) / 1048576 )) \$(( \$(cat /sys/fs/cgroup/memory.max) / 1048576 ))" 2>/dev/null)"
} | PYTHONIOENCODING=utf-8 python tools/gate_producao.py "$@"
