/**
 * T7F.3 · operator-console entry — mode-based routing bootstrap
 *
 * Renders the app inside a `<BrowserRouter>` whose `basename` is derived from
 * the deployment mode reported by `/api/session/mode` (via `useSessionMode`,
 * batch-9 real impl). Single source of truth for mode.
 *
 * Mode policy (spec §3.6 + eval-doc-015 TenantContext middleware):
 *   - master mode                  → basename="/t/<tid>" if the operator's
 *                                    session carries tenant_id (common — an
 *                                    operator is always scoped to a tenant);
 *                                    otherwise "" and we rely on absolute
 *                                    `/t/:tenantId/operator` URLs.
 *   - tenant mode                  → basename="" (URL-flat). The backend
 *                                    middleware rewrites `/t/<self>/*` → `/*`
 *                                    before the SPA loads, so the URL-flat
 *                                    path is the canonical shape in fork
 *                                    deployments.
 *
 * The `<Routes>` tree accepts both URL shapes in both modes — keeps the tree
 * identical across modes and leaves the `basename` as the single
 * mode-dependent knob. No-tenant paths fall through to `NoTenantFallback`.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.6
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { I18nextProvider, createI18n } from '@autoservice/i18n';
import { useSessionMode, type SessionMode } from '@autoservice/shared';
import { App } from './App';
import { NoTenantFallback } from './components/NoTenantFallback';
import './index.css';

const i18n = createI18n();

/**
 * Compute the BrowserRouter basename from the resolved deployment mode +
 * session tenant_id. Exported for unit-test coverage.
 */
export function deriveBasename(
  mode: SessionMode['mode'],
  tenantId: string | null,
): string {
  if (mode === 'tenant') return '';
  if (mode === 'master' && tenantId) return `/t/${tenantId}`;
  return '';
}

function Splash({
  variant = 'loading',
  message,
  onRetry,
}: {
  variant?: 'loading' | 'error';
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      data-testid="operator-splash"
      data-variant={variant}
      role={variant === 'error' ? 'alert' : 'status'}
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        color: '#24292f',
        background:
          'radial-gradient(ellipse at top, #f0f6ff 0%, #ffffff 60%)',
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div
        aria-hidden="true"
        style={{
          width: 48,
          height: 48,
          borderRadius: '50%',
          border: '3px solid #d0d7de',
          borderTopColor: variant === 'error' ? '#cf222e' : '#0969da',
          animation:
            variant === 'loading'
              ? 'operator-splash-spin 0.9s linear infinite'
              : 'none',
        }}
      />
      <div style={{ fontWeight: 600, fontSize: 18 }}>AutoService · Operator</div>
      {message ? (
        <div style={{ color: '#57606a', fontSize: 13 }}>{message}</div>
      ) : null}
      {variant === 'error' && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          data-testid="operator-splash-retry"
          style={{
            marginTop: 4,
            padding: '6px 14px',
            borderRadius: 6,
            border: '1px solid #d0d7de',
            background: '#ffffff',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          Retry
        </button>
      ) : null}
      <style>{'@keyframes operator-splash-spin{to{transform:rotate(360deg)}}'}</style>
    </div>
  );
}

/**
 * Reads `useSessionMode()` and renders the router with the correct basename.
 * Exported for unit tests — tests can inject a fake `fetcher` via the
 * optional prop to drive the three states (loading / error / ready) without
 * hitting a real backend.
 */
export function RouteBootstrap({
  fetcher,
  endpoint,
}: {
  fetcher?: typeof fetch;
  endpoint?: string;
} = {}) {
  const { data, loading, error, refetch } = useSessionMode(fetcher, endpoint);

  if (loading) {
    return <Splash variant="loading" />;
  }

  if (error) {
    return (
      <Splash
        variant="error"
        message="Session check failed — retry to continue."
        onRetry={refetch}
      />
    );
  }

  const mode: SessionMode['mode'] = data?.mode ?? 'master';
  const tenantId = data?.tenant_id ?? null;
  const basename = deriveBasename(mode, tenantId);

  return (
    <BrowserRouter basename={basename || undefined}>
      <Routes>
        {/* Tenant-scoped entry — master mode primary shape */}
        <Route path="/t/:tenantId/operator" element={<App />} />
        {/* URL-flat — tenant mode primary (backend middleware rewrites) */}
        <Route path="/operator" element={<App />} />
        {/* Legacy / no-tenant entry — show a helpful fallback */}
        <Route path="/" element={<NoTenantFallback />} />
        {/* Any other path → back to root */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

// Only mount at module load when a `#root` element is actually present.
// Tests import this module for `RouteBootstrap` / `deriveBasename` coverage
// and should not trigger a real mount.
const rootEl =
  typeof document !== 'undefined' ? document.getElementById('root') : null;
if (rootEl) {
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <I18nextProvider i18n={i18n}>
        <RouteBootstrap />
      </I18nextProvider>
    </React.StrictMode>,
  );
}
