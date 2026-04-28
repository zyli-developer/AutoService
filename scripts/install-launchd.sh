#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

TARGETS="$HOME/Library/LaunchAgents"
mkdir -p "$TARGETS"

for svc in gateway caddy cloudflared; do
  tmpl="deploy/launchd/com.autoservice.$svc.plist.template"
  out="$TARGETS/com.autoservice.$svc.plist"
  [[ -f "$tmpl" ]] || { echo "missing $tmpl"; exit 1; }
  sed -e "s|{{AUTOSERVICE_ROOT}}|$REPO|g" \
      -e "s|{{USER}}|$USER|g" "$tmpl" > "$out"
  echo "wrote $out"
done

for svc in gateway caddy cloudflared; do
  label="com.autoservice.$svc"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$TARGETS/$label.plist"
  launchctl enable "gui/$(id -u)/$label"
  echo "loaded $label"
done

echo
echo "Status:"
for svc in gateway caddy cloudflared; do
  launchctl print "gui/$(id -u)/com.autoservice.$svc" 2>&1 | grep -E 'state|pid' | head -4
done
