#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"

echo "==> Building customer-chat (base=/site/)"
VITE_MOUNT_PATH=/site/    pnpm --filter @autoservice/customer-chat    build

echo "==> Building operator-console (base=/console/)"
VITE_MOUNT_PATH=/console/ pnpm --filter @autoservice/operator-console build

echo "==> Building admin-portal (base=/admin/)"
VITE_MOUNT_PATH=/admin/   pnpm --filter @autoservice/admin-portal     build

echo "==> Built asset references:"
for app in customer-chat operator-console admin-portal; do
  html="apps/$app/dist/index.html"
  echo "  $app:"
  grep -oE '(src|href)="[^"]+"' "$html" | head -3 | sed 's/^/    /'
done
