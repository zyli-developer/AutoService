#!/usr/bin/env bash
# Take the public hostname offline by stopping cloudflared. Gateway
# and Caddy keep running for post-mortem inspection.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

pidfile=".autoservice/run/cloudflared.pid"
if [[ -f "$pidfile" ]]; then
  pid="$(cat "$pidfile")"
  kill "$pid" 2>/dev/null || true
  rm -f "$pidfile"
fi

# Also kill any orphaned cloudflared for our specific UUID.
pkill -f "cloudflared.*389c95d2-6066-437e-854f-8a09b2481259" 2>/dev/null || true

echo "cloudflared stopped; autoservice.ezagent.chat will go 5xx within ~2 seconds."
