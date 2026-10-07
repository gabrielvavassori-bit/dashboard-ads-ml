#!/usr/bin/env bash
# Teste de produção obrigatório após deploy do Dash Ads (ver tools/gate_producao.py).
set -euo pipefail
cd "$(dirname "$0")/.."
K="${RENDER_SSH_KEY:-$LOCALAPPDATA/dashads/ssh/render_diag}"
DASH=srv-d86v0in7f7vs73f3tp5g@ssh.oregon.render.com
AGENT=srv-d88hll6l51nc73fgg8f0@ssh.oregon.render.com
CONTAS="passoapassoecommerce-1478 conta-ativa"
{
  ssh -i "$K" -o BatchMode=yes "$DASH" "cat > /tmp/gate_payload.py; cd /opt/render/project/src && python /tmp/gate_payload.py $CONTAS" < tools/gate_payload.py 2>/dev/null | grep '^GATE_JSON ' || true
  echo "DISK $(ssh -i "$K" -o BatchMode=yes "$AGENT" "df -P /var/data | tail -1" 2>/dev/null | awk '{gsub("%","",$5); print 100-$5}')"
} | PYTHONIOENCODING=utf-8 python tools/gate_producao.py "$@"
