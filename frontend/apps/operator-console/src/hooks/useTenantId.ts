import { useParams } from 'react-router-dom';

/**
 * Extract tenant_id from the current URL.
 *
 * Priority:
 *   1. React Router path param `:tenantId` (e.g. /t/:tenantId/operator)
 *   2. Query string `?tenant=<id>` fallback (useful for direct WS/API smoke)
 *
 * Returns null when neither is present — callers are expected to render a
 * "pick a tenant" fallback rather than connecting with an empty tenant.
 *
 * NOTE: This is a local copy of the shared hook described in T1F.1 /
 * docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2.
 * Once `@autoservice/shared` ships the canonical implementation, replace
 * this file with a re-export so all three SPAs stay in sync.
 */
export function useTenantId(): string | null {
  const params = useParams<{ tenantId?: string }>();
  if (params.tenantId) return params.tenantId;
  if (typeof window === 'undefined') return null;
  const qs = new URLSearchParams(window.location.search).get('tenant');
  return qs ?? null;
}
