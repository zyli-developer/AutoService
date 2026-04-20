/**
 * T1F.5 · admin-portal dual-mode dispatch
 *
 * Queries `GET /api/session/mode` via `useSessionMode` (T1F.2) and renders:
 *   - MasterLayout when the backend reports `mode === "master"` (default)
 *   - TenantLayout stub when the backend reports `mode === "tenant"`
 *
 * While the mode request is in flight we render a minimal loading state;
 * on failure we fall back to MasterLayout so Master deployments (M1 scope)
 * remain usable even if `/api/session/mode` is unreachable — the endpoint
 * only matters once Tenant fork builds ship (M2).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
 */
import { useSessionMode } from '@autoservice/shared';
import { MasterLayout } from './layouts/MasterLayout';
import { TenantLayout } from './layouts/TenantLayout';

export function App() {
  const { data, loading, error } = useSessionMode();

  if (loading) {
    return (
      <div
        data-testid="session-mode-loading"
        style={{ padding: 32, textAlign: 'center' }}
      >
        Loading…
      </div>
    );
  }

  if (error) {
    // Master deployment is the safe default in M1 — the endpoint only
    // exists on master builds and tenant-fork rendering is a stub anyway.
    return <MasterLayout />;
  }

  return data?.mode === 'tenant' ? <TenantLayout /> : <MasterLayout />;
}
