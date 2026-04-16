#!/bin/bash
set -euo pipefail

# ── publish-widget-sdk.sh ──────────────────────────────────────────────
# Build and publish @autoservice/widget-sdk to npm.
# By default runs in --dry-run mode; pass --live to actually publish.
# ───────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

LIVE=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Build and publish @autoservice/widget-sdk to npm.

Options:
  --live    Actually publish (default is dry-run)
  --help    Show this help message

Examples:
  $(basename "$0")          # build + dry-run publish
  $(basename "$0") --live   # build + real publish
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      LIVE=true
      shift
      ;;
    --help|-h)
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

echo "==> Building @autoservice/widget-sdk ..."
cd "$FRONTEND_DIR"
pnpm --filter @autoservice/widget-sdk build

echo ""
if [ "$LIVE" = true ]; then
  echo "==> Publishing @autoservice/widget-sdk (LIVE) ..."
  pnpm --filter @autoservice/widget-sdk publish --no-git-checks
else
  echo "==> Publishing @autoservice/widget-sdk (DRY-RUN) ..."
  pnpm --filter @autoservice/widget-sdk publish --no-git-checks --dry-run
fi

echo ""
echo "Done."
