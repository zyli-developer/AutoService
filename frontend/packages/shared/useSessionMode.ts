/**
 * T6F.1 · useSessionMode — deployment-mode + auth-state hook (M2 real impl)
 *
 * Queries `GET /api/session/mode` (served by `autoservice.api_routes`) and
 * exposes the resulting deployment mode + auth state so admin-portal's
 * `<AuthGate>` can gate rendering and the mode-dispatch in `App.tsx` can
 * select between MasterLayout and TenantLayout.
 *
 * Response shape (batch-8 — spec §4.5):
 *   {
 *     mode: "master" | "tenant",
 *     tenant_id: string | null,
 *     authenticated: boolean,
 *     authenticated_as: string | null,
 *     tier: 0 | 1 | null,
 *     brand_name: string
 *   }
 *
 * The request uses `credentials: "include"` so the HttpOnly `auth_session`
 * cookie set by `/api/auth/verify` is sent. The cookie is invisible to JS
 * (HttpOnly) — the backend is the sole source of truth for auth-state.
 *
 * Implementation note (decision — see eval-doc-011):
 *   Spec §3.6 shows a TanStack Query example; we roll our own vanilla
 *   useState+useEffect hook because admin-portal does not depend on
 *   `@tanstack/react-query`. The signature stays compatible if a future
 *   batch swaps the impl for TanStack Query.
 *
 * Backward compatibility: M1 callers of `useSessionMode()` that only read
 * `data.mode` still work — `mode` is preserved. The M1 `role` field is
 * deprecated (backend no longer returns it); consumers should read
 * `data.authenticated` + `data.authenticated_as` instead.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.6, §4.5
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type SessionMode = {
  mode: 'master' | 'tenant';
  tenant_id: string | null;
  authenticated: boolean;
  authenticated_as: string | null;
  tier: 0 | 1 | null;
  brand_name: string;
  // M1 backward-compat — some callers still read `role`. Backend no longer
  // emits this; we preserve the field as optional so older consumers don't
  // see a type error while they migrate to `authenticated_as`.
  role?: 'platform_admin' | 'tenant_admin';
};

type Result = {
  data: SessionMode | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
};

export function useSessionMode(
  fetcher: typeof fetch = fetch,
  endpoint: string = '/api/session/mode'
): Result {
  const [data, setData] = useState<SessionMode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  // bump this counter to force re-fetch (refetch())
  const [nonce, setNonce] = useState(0);

  // Cancellation flag shared between effect runs — ensures a stale fetch
  // doesn't overwrite state after a newer refetch has been kicked off.
  const latestNonce = useRef(nonce);
  latestNonce.current = nonce;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetcher(endpoint, { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(`/api/session/mode ${r.status}`);
        }
        return (await r.json()) as SessionMode;
      })
      .then((json) => {
        if (!cancelled && latestNonce.current === nonce) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled && latestNonce.current === nonce) {
          setError(e instanceof Error ? e : new Error(String(e)));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetcher, endpoint, nonce]);

  const refetch = useCallback(() => {
    setNonce((n) => n + 1);
  }, []);

  return { data, loading, error, refetch };
}
