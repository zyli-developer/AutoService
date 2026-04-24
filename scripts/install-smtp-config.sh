#!/usr/bin/env bash
# Render .autoservice/config.local.yaml from .smtp.env plus the initial
# admin allowlist. Idempotent; preserves any existing keys outside the
# blocks we manage.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/.smtp.env"
OUT="$REPO/.autoservice/config.local.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. See docs/deploy/public-tunnel-runbook.md." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${SMTP_USER:?SMTP_USER unset in .smtp.env}"
: "${SMTP_FROM:?SMTP_FROM unset in .smtp.env}"
: "${SMTP_PASSWORD:?SMTP_PASSWORD unset in .smtp.env}"
: "${SMTP_HOST:?SMTP_HOST unset}"
: "${SMTP_PORT:=587}"
: "${SMTP_STARTTLS:=true}"

mkdir -p "$(dirname "$OUT")"

cat > "$OUT" <<YAML
# Rendered by scripts/install-smtp-config.sh from .smtp.env
auth:
  admin_emails:
    - lin.yilun@h2oslabs.com
    - huang.jiajia@h2oslabs.com
    - yao.shengyue@h2oslabs.com
    - chen.ruihua@h2oslabs.com
    - autoservice@h2oslabs.com
  smtp:
    host: "$SMTP_HOST"
    port: $SMTP_PORT
    user: "$SMTP_USER"
    password: "$SMTP_PASSWORD"
    from: "$SMTP_FROM"
    starttls: $SMTP_STARTTLS
YAML

chmod 600 "$OUT"
echo "Wrote $OUT (mode 600)."
echo "Next: bash scripts/generate-admin-passwords.sh"
