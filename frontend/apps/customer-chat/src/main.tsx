/**
 * T7F.3 · customer-chat entry — mode-based routing bootstrap
 *
 * Renders the app inside a `<BrowserRouter>` whose `basename` is derived from
 * the deployment mode reported by `/api/session/mode` (via `useSessionMode`,
 * batch-9 real impl). Single source of truth for mode.
 *
 * Mode policy (spec §3.6 + eval-doc-015 TenantContext middleware):
 *   - master mode                  → basename="/t/<tid>" if session.tenant_id
 *                                    is known (rare for a public chat viewer);
 *                                    otherwise "" and we rely on absolute
 *                                    `/t/:tenantId/chat` URLs.
 *   - tenant mode                  → basename="" (URL-flat). The backend
 *                                    middleware rewrites `/t/<self>/*` → `/*`
 *                                    before the SPA loads, so the URL-flat
 *                                    path is the canonical shape in fork
 *                                    deployments.
 *
 * The `<Routes>` tree is a superset that accepts both URL shapes in both
 * modes — this keeps the tree identical across modes and leaves the
 * `basename` as the single mode-dependent knob. Graceful fall-through to the
 * tenant-fallback UI for no-tenant paths (App handles this via useTenantId).
 *
 * Bootstrap lifecycle: because `useSessionMode()` is async, `<RouteBootstrap>`
 * shows a Splash frame (inline spinner, mirrors AuthGate batch-9 pattern)
 * until the mode resolves — no anon content flash (spec §9).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.6
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { I18nextProvider, createI18n, useTranslation } from '@autoservice/i18n';
import { useSessionMode, type SessionMode } from '@autoservice/shared';
import { App } from './App';
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
  const { t } = useTranslation();
  return (
    <div
      data-testid="chat-splash"
      data-variant={variant}
      role={variant === 'error' ? 'alert' : 'status'}
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        color: 'var(--color-text)',
        background:
          'radial-gradient(ellipse at top, var(--indigo-50) 0%, var(--color-bg) 60%)',
        fontFamily: 'var(--font-sans)',
      }}
    >
      <div
        aria-hidden="true"
        style={{
          width: 48,
          height: 48,
          borderRadius: '50%',
          border: '3px solid var(--color-border)',
          borderTopColor: variant === 'error' ? 'var(--color-danger)' : 'var(--color-primary)',
          animation:
            variant === 'loading'
              ? 'chat-splash-spin 0.9s linear infinite'
              : 'none',
        }}
      />
      <div style={{ fontWeight: 600, fontSize: 18 }}>{t('chat.splash.brand')}</div>
      {message ? (
        <div style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>{message}</div>
      ) : null}
      {variant === 'error' && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          data-testid="chat-splash-retry"
          style={{
            marginTop: 4,
            padding: '6px 14px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--color-border)',
            background: 'var(--color-bg-surface)',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          {t('chat.splash.retry')}
        </button>
      ) : null}
      <style>{'@keyframes chat-splash-spin{to{transform:rotate(360deg)}}'}</style>
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
  const { t } = useTranslation();
  const { data, loading, error, refetch } = useSessionMode(fetcher, endpoint);

  if (loading) {
    return <Splash variant="loading" />;
  }

  if (error) {
    return (
      <Splash
        variant="error"
        message={t('chat.splash.session_error')}
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
        {/* Canonical tenant-scoped route — master mode primary shape */}
        <Route path="/t/:tenantId/chat" element={<App />} />
        {/* URL-flat — tenant mode primary (backend middleware rewrites) */}
        <Route path="/chat" element={<App />} />
        {/* Legacy/root entrypoint — App renders tenant-selection fallback */}
        <Route path="*" element={<App />} />
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
