/**
 * T6F.2 · admin-portal root — AuthGate + mode dispatch
 *
 * Dispatch order (top to bottom):
 *   1. `/login`                         → <LoginPage /> (public, no gate)
 *   2. `/tenant/<tid>/admin` path prefix     → <AuthGate> wrapping TenantLayout
 *   3. otherwise                         → <AuthGate> wrapping mode-dispatch
 *      → TenantLayout (session.mode=tenant) or MasterLayout (default)
 *
 * AuthGate (spec §4.5) sits in front of every non-login branch so
 * anonymous visitors get redirected to `/login` without ever flashing
 * MasterLayout frames (first-frame flicker mitigation, spec §9). Because
 * MasterLayout / TenantLayout each wrap their own `<BrowserRouter>` and
 * React Router v6 refuses nested Routers, AuthGate avoids `<Navigate>` and
 * instead drives redirection via `window.location.assign` (see AuthGate).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.6, §4.5
 */
import { useEffect } from 'react';
import { useSessionMode } from '@autoservice/shared';
import { useAdminStore } from './store/adminStore';
import { AuthGate } from './components/auth/AuthGate';
import { LoginPage } from './components/auth/LoginPage';
import { MasterLayout } from './layouts/MasterLayout';
import { TenantLayout } from './layouts/TenantLayout';

/**
 * Extract tenant id from a `/tenant/<tid>/admin` pathname. Returns null for any
 * other shape.
 */
function tenantIdFromAdminPath(pathname: string): string | null {
  const match = pathname.match(/^\/tenant\/([^/]+)\/admin(?:\/|$)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Mode dispatcher — rendered INSIDE `<AuthGate>`. By the time this runs
 * `data.authenticated === true` (AuthGate has redirected otherwise).
 */
function ModeDispatch() {
  const { data } = useSessionMode();
  if (data?.mode === 'tenant') {
    return <TenantLayout tenantId={data.tenant_id ?? undefined} />;
  }
  return <MasterLayout />;
}

export function App() {
  const pathname =
    typeof window !== 'undefined' ? window.location.pathname : '';
  const pathTenantId = tenantIdFromAdminPath(pathname);

  const { data } = useSessionMode();
  const setTenantId = useAdminStore((s) => s.setTenantId);

  useEffect(() => {
    // URL path-tenant wins over session (matches useTenantId semantics at
    // frontend/packages/shared/useTenantId.ts:50-51). When neither is
    // present (anon or master session), clear any stale persisted value.
    setTenantId(pathTenantId ?? data?.tenant_id ?? null);
  }, [pathTenantId, data?.tenant_id, setTenantId]);

  // `/login` public — no gate.
  if (pathname === '/login' || pathname.startsWith('/login/')) {
    return <LoginPage />;
  }

  // `/tenant/<tid>/admin` path-tenant short-circuit (preserved from M1). Must
  // still pass through AuthGate so anon visitors don't see the tenant
  // shell before the redirect.
  if (pathTenantId) {
    return (
      <AuthGate>
        <TenantLayout tenantId={pathTenantId} />
      </AuthGate>
    );
  }

  return (
    <AuthGate>
      <ModeDispatch />
    </AuthGate>
  );
}
