/**
 * T1F.5 · TenantLayout — tenant operator (B) view
 *
 * M1 stub. Renders when the backend reports `mode === "tenant"` (Tenant fork
 * deployment). The real tenant-specific admin UI lands in M2; in M1 we only
 * need the dispatch path to exist so a Tenant fork build can still boot.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
 */
export function TenantLayout() {
  return (
    <div
      data-testid="tenant-layout-stub"
      style={{ padding: 32, textAlign: 'center' }}
    >
      <h2>Tenant view</h2>
      <p>This deployment is running in tenant mode.</p>
      <p>The tenant-specific admin UI is not yet available in M1.</p>
      <p>Contact the platform operator.</p>
    </div>
  );
}
