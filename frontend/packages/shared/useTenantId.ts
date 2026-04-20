/**
 * T1F.1 · useTenantId — shared tenant-id extraction hook
 *
 * Returns the current tenant id by inspecting (in priority order):
 *  1. The `:tenantId` route path parameter (matches `/t/:tenantId/*`)
 *  2. The `?tenant=` query string parameter (read from the router's location,
 *     with a `window.location` fallback for non-router callers)
 *
 * Returns `null` when neither is present. Safe to call from SSR contexts
 * (guards `window` access).
 *
 * Consumers: customer-chat, operator-console, admin-portal — unblocks
 * GAP-004 (multi-tenant SDK routing) by replacing hardcoded WS URLs like
 * `ws://localhost:8000/ws/customer` with `?tenant=<useTenantId()>`.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.1, §5.2
 */
import { useLocation, useParams } from 'react-router-dom';

export function useTenantId(): string | null {
  // Hooks must be called unconditionally (React Rules of Hooks).
  const params = useParams<{ tenantId?: string }>();
  const routerLocation = useLocation();

  if (params.tenantId) return params.tenantId;

  // Prefer the router's own location (works under MemoryRouter in tests);
  // fall back to `window.location.search` for callers that sit outside a Router.
  let search = routerLocation?.search ?? '';
  if (!search && typeof window !== 'undefined') {
    search = window.location.search;
  }

  try {
    return new URLSearchParams(search).get('tenant');
  } catch {
    return null;
  }
}
