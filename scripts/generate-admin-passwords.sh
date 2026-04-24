#!/usr/bin/env bash
# For every email in .autoservice/config.local.yaml::auth.admin_emails
# that does NOT yet have an entry in .autoservice/passwords.json,
# generate a random password, bcrypt-hash it, and append the entry.
# Plaintext passwords are printed ONCE at the end with a warning.
# Idempotent: rerunning skips emails that already have entries.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$REPO/.autoservice/config.local.yaml"
PWFILE="$REPO/.autoservice/passwords.json"

if [[ ! -f "$CFG" ]]; then
  echo "ERROR: $CFG not found. Run scripts/install-smtp-config.sh first." >&2
  exit 1
fi
command -v yq >/dev/null 2>&1 || { echo "ERROR: brew install yq" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: brew install jq" >&2; exit 3; }

mapfile -t emails < <(yq e '.auth.admin_emails[]' "$CFG")
[[ ${#emails[@]} -gt 0 ]] || { echo "No admin_emails in $CFG"; exit 4; }

if [[ ! -f "$PWFILE" ]]; then
  echo '{"version":1,"updated_at":"","entries":[]}' > "$PWFILE"
  chmod 600 "$PWFILE"
fi

declare -a newly_generated_emails=()
declare -a newly_generated_passwords=()

for email in "${emails[@]}"; do
  exists="$(jq --arg e "$email" '[.entries[] | select(.email==$e)] | length' "$PWFILE")"
  if [[ "$exists" != "0" ]]; then
    continue
  fi

  pw="$(cd "$REPO" && uv run python -c 'import secrets; print(secrets.token_urlsafe(16))')"
  hash="$(cd "$REPO" && printf '%s' "$pw" | uv run python -c '
import sys, bcrypt
pw = sys.stdin.read().encode()
print(bcrypt.hashpw(pw, bcrypt.gensalt(12)).decode(), end="")
')"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  tmp="$(mktemp)"
  jq --arg email "$email" --arg h "$hash" --arg now "$now" \
     '.entries += [{"email":$email,"password_bcrypt":$h,"generated_at":$now}] | .updated_at = $now' \
     "$PWFILE" > "$tmp"
  mv "$tmp" "$PWFILE"
  chmod 600 "$PWFILE"

  newly_generated_emails+=("$email")
  newly_generated_passwords+=("$pw")
done

if [[ ${#newly_generated_emails[@]} -eq 0 ]]; then
  echo "No new passwords generated — all admin_emails already have entries."
  exit 0
fi

echo
echo "======================================================================"
echo "  NEW ADMIN PASSWORDS — NOT SHOWN AGAIN. DISTRIBUTE SECURELY."
echo "======================================================================"
for i in "${!newly_generated_emails[@]}"; do
  printf "  %-40s  %s\n" "${newly_generated_emails[$i]}" "${newly_generated_passwords[$i]}"
done
echo "======================================================================"
echo
echo "Run 'make public-reload' if the gateway is already running."
