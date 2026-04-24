#!/usr/bin/env bash
# Build the three subpath-mounted Vite bundles for the public tunnel
# deploy. We invoke `vite build` directly (skipping the per-package
# `build` script which chains `tsc --noEmit && vite build`) because the
# existing codebase has pre-existing tsc errors on main that are
# unrelated to the deploy work. CI / local dev still run the full
# `pnpm build` for type safety; this script is the demo-deploy
# fast-path.
set -euo pipefail
cd "$(dirname "$0")/../frontend"

PNPM="pnpm --config.engine-strict=false"

echo "==> Building customer-chat (base=/site/)"
VITE_MOUNT_PATH=/site/    $PNPM --filter @autoservice/customer-chat    exec vite build

echo "==> Building operator-console (base=/console/)"
VITE_MOUNT_PATH=/console/ $PNPM --filter @autoservice/operator-console exec vite build

echo "==> Building admin-portal (base=/admin/)"
VITE_MOUNT_PATH=/admin/   $PNPM --filter @autoservice/admin-portal     exec vite build

echo "==> Built asset references:"
for app in customer-chat operator-console admin-portal; do
  html="apps/$app/dist/index.html"
  echo "  $app:"
  grep -oE '(src|href)="[^"]+"' "$html" | head -3 | sed 's/^/    /'
done
