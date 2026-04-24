#!/usr/bin/env bash
# Full reload: rebuild frontends, restart gateway (new Python code),
# restart cloudflared (drop long-lived WS so clients reconnect against
# the new code). Caddy does NOT need restart — file_server reads from
# disk on every request.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "==> Rebuilding frontends"
bash scripts/public-build.sh

echo "==> Restarting gateway"
if [[ -f .autoservice/run/gateway.pid ]]; then
  kill "$(cat .autoservice/run/gateway.pid)" 2>/dev/null || true
  rm -f .autoservice/run/gateway.pid
  sleep 1
fi
PLACEHOLDER_ENABLED=0 \
CORS_EXTRA_ORIGINS="https://autoservice.ezagent.chat" \
nohup uv run uvicorn autoservice.web_gateway:create_app \
  --factory --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" \
  --log-level info \
  >> .autoservice/logs/gateway.log 2>&1 &
echo $! > .autoservice/run/gateway.pid
disown

echo "==> Restarting cloudflared (drops existing WS)"
if [[ -f .autoservice/run/cloudflared.pid ]]; then
  kill "$(cat .autoservice/run/cloudflared.pid)" 2>/dev/null || true
  rm -f .autoservice/run/cloudflared.pid
  sleep 1
fi
nohup /opt/homebrew/bin/cloudflared tunnel \
  --config /Users/$USER/.cloudflared/autoservice.yml run 389c95d2-6066-437e-854f-8a09b2481259 \
  >> .autoservice/logs/cloudflared-stdout.log 2>&1 &
echo $! > .autoservice/run/cloudflared.pid
disown

sleep 3
echo "Reload complete."
