#!/bin/bash
set -euo pipefail

# NFR-4 Co-location Policy Check
# Validates that bridges service uses network_mode: "service:channel-server"
# in docker-compose template and all rendered tenant compose files.
#
# Usage:
#   deploy/check-colocation.sh                  # check template + all tenants
#   deploy/check-colocation.sh --file <path>    # check a specific compose file
#   deploy/check-colocation.sh --help

SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "$0")" && pwd)}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

NFR-4 co-location policy check. Ensures bridges and channel-server
share the same network namespace (network_mode: "service:channel-server").

Options:
  --file <path>   Check a specific docker-compose YAML file
  --help          Show this help message

Without --file, checks:
  1. deploy/docker-compose.tmpl.yaml (template)
  2. deploy/tenants/*/docker-compose.yml (all rendered tenants)

Exit codes:
  0  All checks passed
  1  Policy violation detected
EOF
}

check_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "SKIP: $file (not found)"
    return 0
  fi

  # Extract bridges service's network_mode value
  # Handles both quoted and unquoted YAML values
  local network_mode
  network_mode=$(grep -A 20 '^\s*bridges:' "$file" \
    | grep 'network_mode:' \
    | head -1 \
    | sed 's/.*network_mode:\s*//' \
    | tr -d '"' \
    | tr -d "'" \
    | xargs)

  if [[ -z "$network_mode" ]]; then
    echo "FAIL: $file — bridges service missing network_mode"
    return 1
  fi

  if [[ "$network_mode" != "service:channel-server" ]]; then
    echo "FAIL: $file — bridges.network_mode='$network_mode' (expected 'service:channel-server')"
    return 1
  fi

  echo "PASS: $file"
  return 0
}

# Parse args
TARGET_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      TARGET_FILE="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

FAILURES=0

if [[ -n "$TARGET_FILE" ]]; then
  check_file "$TARGET_FILE" || FAILURES=$((FAILURES + 1))
else
  # Check template
  check_file "$SCRIPT_DIR/docker-compose.tmpl.yaml" || FAILURES=$((FAILURES + 1))

  # Check all rendered tenant compose files
  if [[ -d "$SCRIPT_DIR/tenants" ]]; then
    for tenant_dir in "$SCRIPT_DIR"/tenants/*/; do
      compose="$tenant_dir/docker-compose.yml"
      if [[ -f "$compose" ]]; then
        check_file "$compose" || FAILURES=$((FAILURES + 1))
      fi
    done
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo ""
  echo "NFR-4 VIOLATION: $FAILURES file(s) failed co-location check."
  echo "See: docs/deploy/nfr4-colocation-policy.md"
  exit 1
fi

echo ""
echo "NFR-4: All co-location checks passed."
