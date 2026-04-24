/**
 * operator-console entry — mounts the SPA inside BrowserRouter after
 * /api/session/mode resolves (Splash covers the async bootstrap). The
 * route table matches `/tenant/:tenantId/operator` (master canonical) and
 * `/operator` (tenant canonical after backend URL rewrite) directly; no
 * basename stripping, because the app has no relative navigation.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { I18nextProvider, createI18n, useTranslation } from '@autoservice/i18n';
import { useSessionMode } from '@autoservice/shared';
import { App } from './App';
import { NoTenantFallback } from './components/NoTenantFallback';
import './index.css';

const i18n = createI18n();

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
              ? 'operator-splash-spin 0.9s linear infinite'
              : 'none',
        }}
      />
      <div style={{ fontWeight: 600, fontSize: 18 }}>{t('operator.splash.brand')}</div>
      {message ? (
        <div style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>{message}</div>
      ) : null}
      {variant === 'error' && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          data-testid="operator-splash-retry"
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
          {t('operator.splash.retry')}
        </button>
      ) : null}
      <style>{'@keyframes operator-splash-spin{to{transform:rotate(360deg)}}'}</style>
    </div>
  );
}

/**
 * Gates rendering on `useSessionMode()` so the Splash covers the async
 * handshake. Exported for unit tests — tests can inject a fake `fetcher`
 * via the optional prop to drive loading / error / ready states without
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
  const { loading, error, refetch } = useSessionMode(fetcher, endpoint);

  if (loading) {
    return <Splash variant="loading" />;
  }

  if (error) {
    return (
      <Splash
        variant="error"
        message={t('operator.splash.session_error')}
        onRetry={refetch}
      />
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        {/* Tenant-scoped entry — master mode primary shape */}
        <Route path="/tenant/:tenantId/operator" element={<App />} />
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
// Tests import this module for `RouteBootstrap` coverage and should not
// trigger a real mount.
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
