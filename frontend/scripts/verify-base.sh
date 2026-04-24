#!/usr/bin/env bash
# Builds customer-chat with VITE_MOUNT_PATH=/site/ and asserts the emitted
# index.html references /site/assets/ — proving base is parameterized.
set -euo pipefail
cd "$(dirname "$0")/.."

VITE_MOUNT_PATH=/site/ pnpm --filter @autoservice/customer-chat build >/dev/null
html="apps/customer-chat/dist/index.html"
grep -q 'src="/site/assets/' "$html" \
  && grep -q 'href="/site/assets/' "$html" \
  && echo "OK: customer-chat dist references /site/assets/" \
  || { echo "FAIL: base not applied"; exit 1; }
