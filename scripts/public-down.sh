#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

for name in caddy cloudflared gateway; do
  pidfile=".autoservice/run/$name.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if ps -p "$pid" -o pid= >/dev/null 2>&1; then
      echo "  stopping $name (pid=$pid)"
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done

for port in 18080 8000; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  for pid in $pids; do
    echo "  freeing port $port (pid=$pid)"
    kill -9 "$pid" 2>/dev/null || true
  done
done
