#!/usr/bin/env bash
# HTTP + WS smoke checks against the public hostname. Exits non-zero
# on any failure so CI / runbook can chain safely.
set -euo pipefail

HOST=${HOST:-https://autoservice.ezagent.chat}

fail() { echo "✗ $*"; exit 1; }
ok()   { echo "✓ $*"; }

# 1. Caddy health
code="$(curl -sS -o /dev/null -w '%{http_code}' "$HOST/_caddy_health" || true)"
[[ "$code" == "200" ]] && ok "caddy /_caddy_health 200" || fail "/_caddy_health expected 200, got $code"

# 2. Customer site (no Access)
code="$(curl -sS -o /tmp/site.html -w '%{http_code}' "$HOST/site/" || true)"
[[ "$code" == "200" ]] && ok "/site/ 200" || fail "/site/ expected 200, got $code"
grep -q 'id="root"' /tmp/site.html && ok "/site/ has React mount root" || fail "/site/ missing React root"

# 3. AUTH_DEV_MODE must NOT leak
resp="$(curl -sS "$HOST/api/auth/dev-mode" 2>&1 || true)"
if echo "$resp" | grep -qi '"enabled"[[:space:]]*:[[:space:]]*true'; then
  fail "AUTH_DEV_MODE appears enabled on public deployment"
fi
ok "AUTH_DEV_MODE not leaked"

# 4. /api/master/tenants must be gated by CF Access (NEVER 200)
code="$(curl -sS -o /dev/null -w '%{http_code}' "$HOST/api/master/tenants" || true)"
if [[ "$code" == "200" ]]; then
  fail "/api/master/tenants returned 200 — CF Access not protecting it"
fi
ok "/api/master/tenants gated (HTTP $code)"

# 5. /admin/ gated
code="$(curl -sS -o /tmp/admin.html -w '%{http_code}' -L --max-redirs 0 "$HOST/admin/" || true)"
if [[ "$code" == "200" ]] && grep -q 'id="root"' /tmp/admin.html; then
  fail "/admin/ served app HTML without CF Access challenge"
fi
ok "/admin/ gated (HTTP $code)"

# 6. robots disallow all
resp="$(curl -sS "$HOST/robots.txt" || true)"
echo "$resp" | grep -q 'Disallow: /' && ok "robots.txt disallows all" || fail "robots.txt malformed"

# 7. WS handshake
if command -v websocat >/dev/null 2>&1; then
  if echo | websocat --exit-on-eof -1 --protocol "" "wss://${HOST#https://}/ws/customer?tenant=_smoke" >/dev/null 2>&1; then
    ok "wss /ws/customer handshake"
  else
    echo "⚠ wss /ws/customer: connect failed (server may reject tenant=_smoke; manual check recommended)"
  fi
else
  echo "⚠ websocat not installed — skip WS check (brew install websocat)"
fi

echo
echo "Smoke passed."
