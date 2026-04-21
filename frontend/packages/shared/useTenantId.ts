/**
 * T6F.1 · useTenantId — tenant-id extraction hook (M2 real impl)
 *
 * Resolution order (spec §3.6):
 *  1. The `:tenantId` route path param (matches `/t/:tenantId/*`) — URL wins
 *     in ALL modes because deep links are authoritative. A fork admin
 *     browsing `/t/other/admin` sees `other` (backend middleware will 403
 *     the cross-tenant access, which is the desired UX — not a silent
 *     substitution).
 *  2. The `?tenant=` query-string parameter — legacy fallback.
 *  3. `useSessionMode().data.tenant_id` — when no URL scope and the backend
 *     reports `mode === "tenant"` (fork deployment), the session's own
 *     tenant_id is the correct identity.
 *  4. `null` — master mode with no URL scope = no tenant context.
 *
 * Safe to call from SSR contexts (guards `window`), outside a router
 * (but at minimum inside a `<Router>` — `useLocation` would throw
 * otherwise; callers that need a router-less fallback should use the
 * `_unsafeUseTenantIdNoRouter` export).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.6
 */
import { useLocation, useParams } from 'react-router-dom';

import { useSessionMode } from './useSessionMode';

export function useTenantId(): string | null {
  // Hooks must run unconditionally — we always call all three even if the
  // first yields a value.
  const params = useParams<{ tenantId?: string }>();
  const routerLocation = useLocation();
  const { data: session } = useSessionMode();

  if (params.tenantId) return params.tenantId;

  let search = routerLocation?.search ?? '';
  if (!search && typeof window !== 'undefined') {
    search = window.location.search;
  }

  try {
    const fromQuery = new URLSearchParams(search).get('tenant');
    if (fromQuery) return fromQuery;
  } catch {
    // ignore malformed query string
  }

  // Session fallback — only when backend reports fork mode. In master mode
  // we return null so the caller can render the tenant-list / master view.
  if (session && session.mode === 'tenant' && session.tenant_id) {
    return session.tenant_id;
  }

  return null;
}
