#!/usr/bin/env bash
# Apply deploy/cloudflare-access/allowlist.yml to Cloudflare Access via
# the REST API. Degrades gracefully: if CF_API_TOKEN / CF_ACCOUNT_ID
# are absent, print the equivalent curl commands for manual execution.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
YML="$REPO/deploy/cloudflare-access/allowlist.yml"
ENV_FILE="$REPO/.cf-access.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

command -v yq >/dev/null 2>&1 || { echo "ERROR: brew install yq" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: brew install jq" >&2; exit 2; }

DOMAIN="$(yq e '.application.domain' "$YML")"
NAME="$(yq e '.application.name' "$YML")"
SESSION="$(yq e '.application.session_duration' "$YML")"
APP_TYPE="$(yq e '.application.type // "self_hosted"' "$YML")"
EMAILS_JSON="$(yq e -o=json '.allowed_emails' "$YML")"
INCLUDE="$(echo "$EMAILS_JSON" | jq '[.[] | {email: {email: .}}]')"

if [[ -z "${CF_API_TOKEN:-}" || -z "${CF_ZONE_ID:-}" ]]; then
  cat <<EOF
CF_API_TOKEN or CF_ZONE_ID unset — printing curl commands for manual run.

# 1) Create Access Application (zone-scoped)
curl -X POST https://api.cloudflare.com/client/v4/zones/\${CF_ZONE_ID}/access/apps \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"$NAME","domain":"$DOMAIN","session_duration":"$SESSION","type":"$APP_TYPE"}'

# 2) Attach allow policy
curl -X POST https://api.cloudflare.com/client/v4/zones/\${CF_ZONE_ID}/access/apps/<APP_UUID>/policies \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"allow-team","decision":"allow","include":'"$INCLUDE"'}'
EOF
  exit 0
fi

api() { curl -s "$@" -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json"; }
# Zone-scoped Access endpoint. Account-scoped (/accounts/$ID/access/apps)
# requires the Zero Trust "team" bootstrap which we don't rely on for
# a single-zone demo.
base="https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/access/apps"

# Gather protected paths from yml; turn each into `domain + path` for
# the CF Access application. The CF `domain` field accepts path globs
# (e.g. autoservice.ezagent.chat/admin*) — each becomes its own app.
PROTECTED_PATHS=()
while IFS= read -r p; do
  PROTECTED_PATHS+=("$p")
done < <(yq e '.protected_paths[]' "$YML")

# Reap any previous app whose domain doesn't belong to our path list
# (e.g. an old whole-hostname app created before path-selective mode).
echo "==> Removing stale Access apps for $DOMAIN"
existing_json="$(api "$base")"
echo "$existing_json" | jq -r --arg d "$DOMAIN" '
  .result[]?
  | select(.domain | startswith($d))
  | [.id, .domain] | @tsv
' | while IFS=$'\t' read -r id dom; do
  # Keep only apps whose domain matches a path we still want to protect.
  keep=0
  for p in "${PROTECTED_PATHS[@]}"; do
    want="$DOMAIN$p"
    if [[ "$dom" == "$want" ]]; then
      keep=1
      break
    fi
  done
  if [[ "$keep" == "0" ]]; then
    echo "  deleting $id ($dom)"
    api -X DELETE "$base/$id" >/dev/null
  fi
done

# Refresh list for upsert loop.
existing_json="$(api "$base")"

echo "==> Upserting protected-path apps"
for path in "${PROTECTED_PATHS[@]}"; do
  app_domain="$DOMAIN$path"
  app_name="${NAME}-$(echo "$path" | sed -e 's|[^A-Za-z0-9]|_|g' -e 's|^_||' -e 's|_$||')"
  app_body=$(jq -n --arg n "$app_name" --arg d "$app_domain" --arg s "$SESSION" --arg t "$APP_TYPE" \
    '{name:$n,domain:$d,session_duration:$s,type:$t}')

  existing_id="$(echo "$existing_json" | jq -r --arg d "$app_domain" '.result[]? | select(.domain==$d) | .id' | head -1)"
  if [[ -n "$existing_id" && "$existing_id" != "null" ]]; then
    app_id="$existing_id"
    api -X PUT "$base/$app_id" -d "$app_body" >/dev/null
    echo "  updated  $app_domain  ($app_id)"
  else
    app_id="$(api -X POST "$base" -d "$app_body" | jq -r '.result.id // ""')"
    if [[ -z "$app_id" ]]; then
      echo "  FAILED to create $app_domain"; continue
    fi
    echo "  created  $app_domain  ($app_id)"
  fi

  # Upsert the allow policy.
  policies_url="$base/$app_id/policies"
  pol_id="$(api "$policies_url" | jq -r '.result[]? | select(.name=="allow-team") | .id' | head -1)"
  pol_body=$(jq -n --argjson inc "$INCLUDE" '{name:"allow-team",decision:"allow",include:$inc,precedence:1}')
  if [[ -n "$pol_id" && "$pol_id" != "null" ]]; then
    api -X PUT "$policies_url/$pol_id" -d "$pol_body" >/dev/null
  else
    api -X POST "$policies_url" -d "$pol_body" >/dev/null
  fi
done

echo
echo "==> Applied. Paths NOT listed above are left uncovered (bypass by omission)."
