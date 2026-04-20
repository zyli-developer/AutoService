/**
 * T1F.2 · useSessionMode — deployment-mode detection hook
 *
 * Queries `GET /api/session/mode` (served by `autoservice.api_routes`) and
 * exposes the resulting deployment mode so admin-portal can render either
 * MasterLayout (platform_admin) or TenantLayout (tenant_admin).
 *
 * M1 contract — master deployment only:
 *   { mode: "master", role: "platform_admin" }
 *
 * M2 contract — tenant fork deployment adds `tenant_id`:
 *   { mode: "tenant", role: "tenant_admin", tenant_id: "<tid>" }
 *
 * The `fetcher` parameter is injectable so tests can provide a mock without
 * touching the real network. Defaults to the global `fetch`.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
 */
import { useEffect, useState } from 'react';

export type SessionMode = {
  mode: 'master' | 'tenant';
  role: 'platform_admin' | 'tenant_admin';
  tenant_id?: string;
};

type Result = {
  data: SessionMode | null;
  loading: boolean;
  error: Error | null;
};

export function useSessionMode(
  fetcher: typeof fetch = fetch,
  endpoint: string = '/api/session/mode'
): Result {
  const [data, setData] = useState<SessionMode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetcher(endpoint)
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(`/api/session/mode ${r.status}`);
        }
        return (await r.json()) as SessionMode;
      })
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e : new Error(String(e)));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetcher, endpoint]);

  return { data, loading, error };
}
