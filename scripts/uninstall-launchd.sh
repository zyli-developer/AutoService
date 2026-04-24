#!/usr/bin/env bash
set -euo pipefail
TARGETS="$HOME/Library/LaunchAgents"
for svc in gateway caddy cloudflared; do
  label="com.autoservice.$svc"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$TARGETS/$label.plist"
  echo "removed $label"
done
