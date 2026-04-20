import { useParams, useSearchParams } from 'react-router-dom';

/**
 * Returns the tenant ID for the current request.
 *
 * Resolution order (first match wins):
 *   1. Path parameter `:tenantId` from the route `/t/:tenantId/chat`.
 *   2. Query string `?tenant=<id>` — used when the app is mounted at `/chat`
 *      (fork-side layout) without the `/t/<id>/` prefix.
 *
 * Returns `null` when neither is present. Callers should render a
 * tenant-selection fallback UI in that case instead of connecting.
 *
 * NOTE: T1F.1 nominally provides this hook from `@autoservice/shared`.
 * Until that package lands we keep a local copy here; the behaviour is
 * intentionally kept narrow so the cross-over is mechanical.
 */
export function useTenantId(): string | null {
  const params = useParams<{ tenantId?: string }>();
  const [searchParams] = useSearchParams();
  const fromPath = params.tenantId?.trim();
  if (fromPath) return fromPath;
  const fromQuery = searchParams.get('tenant')?.trim();
  return fromQuery ? fromQuery : null;
}
