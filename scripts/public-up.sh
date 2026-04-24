#!/usr/bin/env bash
# Start gateway + Caddy + (if not running) cloudflared as backgrounded
# user processes. Tracks PIDs under .autoservice/run/. AUTH_DEV_MODE
# is unset defensively — public deploy must NEVER have it set.
set -euo pipefail
unset AUTH_DEV_MODE

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

mkdir -p .autoservice/logs .autoservice/run

: "${CADDY_PORT:=18080}"
export CADDY_PORT
export AUTOSERVICE_ROOT="$REPO"

if lsof -nP -iTCP:$CADDY_PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: port $CADDY_PORT already in use:"
  lsof -nP -iTCP:$CADDY_PORT -sTCP:LISTEN
  exit 1
fi

echo "==> Starting gateway (127.0.0.1:8000)"
PLACEHOLDER_ENABLED=0 \
CORS_EXTRA_ORIGINS="https://autoservice.ezagent.chat" \
nohup uv run uvicorn autoservice.web_gateway:create_app \
  --factory --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" \
  --log-level info \
  >> .autoservice/logs/gateway.log 2>&1 &
echo $! > .autoservice/run/gateway.pid
disown

sleep 1

echo "==> Starting Caddy (127.0.0.1:$CADDY_PORT)"
nohup /usr/local/bin/caddy run \
  --adapter caddyfile \
  --config "$REPO/deploy/caddy/Caddyfile.public" \
  >> .autoservice/logs/caddy-stdout.log 2>&1 &
echo $! > .autoservice/run/caddy.pid
disown

sleep 1

TUNNEL_UUID=389c95d2-6066-437e-854f-8a09b2481259
if pgrep -f "cloudflared.*$TUNNEL_UUID" >/dev/null 2>&1; then
  echo "==> cloudflared already running for $TUNNEL_UUID — skipping"
else
  echo "==> Starting cloudflared"
  nohup /opt/homebrew/bin/cloudflared tunnel \
    --config /Users/$USER/.cloudflared/autoservice.yml run "$TUNNEL_UUID" \
    >> .autoservice/logs/cloudflared-stdout.log 2>&1 &
  echo $! > .autoservice/run/cloudflared.pid
  disown
fi

sleep 2
echo
echo "==> Status"
for p in gateway caddy cloudflared; do
  pidfile=".autoservice/run/$p.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if ps -p "$pid" -o pid= >/dev/null 2>&1; then
      echo "  $p UP (pid=$pid)"
    else
      echo "  $p DEAD (pidfile stale)"
    fi
  fi
done

echo
echo "Caddy health:   curl -I http://127.0.0.1:$CADDY_PORT/_caddy_health"
echo "Gateway health: curl -I http://127.0.0.1:8000/docs"
echo "Public:         curl -I https://autoservice.ezagent.chat/_caddy_health"
