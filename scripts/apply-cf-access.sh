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

if [[ -z "${CF_API_TOKEN:-}" || -z "${CF_ACCOUNT_ID:-}" ]]; then
  cat <<EOF
CF_API_TOKEN or CF_ACCOUNT_ID unset — printing curl commands for manual run.

# 1) Create Access Application
curl -X POST https://api.cloudflare.com/client/v4/accounts/\${CF_ACCOUNT_ID}/access/apps \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"$NAME","domain":"$DOMAIN","session_duration":"$SESSION","type":"$APP_TYPE"}'

# 2) Attach allow policy
curl -X POST https://api.cloudflare.com/client/v4/accounts/\${CF_ACCOUNT_ID}/access/apps/<APP_UUID>/policies \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"allow-team","decision":"allow","include":'"$INCLUDE"'}'
EOF
  exit 0
fi

api() { curl -s "$@" -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json"; }
base="https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps"

existing="$(api "$base" | jq -r --arg d "$DOMAIN" '.result[] | select(.domain==$d) | .id' | head -1)"

app_body=$(jq -n --arg n "$NAME" --arg d "$DOMAIN" --arg s "$SESSION" --arg t "$APP_TYPE" \
  '{name:$n,domain:$d,session_duration:$s,type:$t}')

if [[ -n "$existing" && "$existing" != "null" ]]; then
  echo "Updating existing app $existing"
  app_id="$existing"
  api -X PUT "$base/$app_id" -d "$app_body" | jq '.success'
else
  echo "Creating new Access application"
  app_id="$(api -X POST "$base" -d "$app_body" | jq -r '.result.id')"
  echo "Created app_id=$app_id"
fi

policies_url="$base/$app_id/policies"
policy_id="$(api "$policies_url" | jq -r '.result[] | select(.name=="allow-team") | .id' | head -1)"
policy_body=$(jq -n --argjson inc "$INCLUDE" '{name:"allow-team",decision:"allow",include:$inc,precedence:1}')

if [[ -n "$policy_id" && "$policy_id" != "null" ]]; then
  echo "Updating policy $policy_id"
  api -X PUT "$policies_url/$policy_id" -d "$policy_body" | jq '.success'
else
  echo "Creating allow-team policy"
  api -X POST "$policies_url" -d "$policy_body" | jq '.success'
fi

echo "Applied. App ID: $app_id"
echo "NOTE: public_paths (bypass rules) in allowlist.yml must be configured as separate CF Access applications with decision=bypass — see runbook §Applying CF Access manually."
