#!/usr/bin/env bash
# Full reload: rebuild frontends, restart gateway (new Python code),
# restart cloudflared (drop long-lived WS so clients reconnect against
# the new code). Caddy does NOT need restart — file_server reads from
# disk on every request.
#
# launchd-aware: if a launchd agent is loaded we use `launchctl
# kickstart -k` (which gives us a fresh PID); otherwise we fall back
# to the manual PID-file + nohup flow used by public-up.sh.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

is_launchd() {
  local label="$1"
  launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1
}

restart_launchd() {
  local label="$1"
  local before_pid
  before_pid="$(launchctl print "gui/$(id -u)/$label" 2>&1 | awk '/pid =/ {print $3; exit}')"
  launchctl kickstart -k "gui/$(id -u)/$label"
  sleep 2
  local after_pid
  after_pid="$(launchctl print "gui/$(id -u)/$label" 2>&1 | awk '/pid =/ {print $3; exit}')"
  if [[ -n "$after_pid" && "$before_pid" != "$after_pid" ]]; then
    echo "  $label restarted: $before_pid -> $after_pid"
  else
    echo "  $label restart uncertain (before=$before_pid after=$after_pid)"
  fi
}

restart_nohup_gateway() {
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
}

restart_nohup_cloudflared() {
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
}

echo "==> Rebuilding frontends"
bash scripts/public-build.sh

echo "==> Restarting gateway"
if is_launchd com.autoservice.gateway; then
  restart_launchd com.autoservice.gateway
else
  restart_nohup_gateway
fi

echo "==> Restarting cloudflared (drops existing WS)"
if is_launchd com.autoservice.cloudflared; then
  restart_launchd com.autoservice.cloudflared
else
  restart_nohup_cloudflared
fi

sleep 2
echo "Reload complete."
