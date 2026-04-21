/**
 * T6F.2 · LoginPage — magic-link request form
 *
 * POSTs the admin's email to `/api/auth/request-login` (batch-7 endpoint).
 * The backend always replies 200 (anti-enumeration per spec §5.2); on
 * success we flip to a "check your inbox" confirmation state.
 *
 * Dev-mode hint: when served from `localhost`, we surface a note pointing
 * at `.autoservice/logs/auth-devmail.jsonl` where the magic link is
 * logged when SMTP is not configured (spec §5.6).
 *
 * NOTE: this file coexists with the legacy `components/LoginPage.tsx`
 * (tenant-id-based login used by `MasterLayout`'s zustand `isLoggedIn`
 * flow). M2 will eventually remove the legacy one once `MasterLayout`
 * drops its internal gate and delegates to `<AuthGate>`.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5, §5.2
 */
import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';

interface LoginPageProps {
  /**
   * Optional tenant id; when present, the request-login payload carries it
   * so the backend can mint a tier-1 session scoped to the tenant.
   * Admin-portal defaults to null (tier-0 master admin); a fork-deployed
   * tenant-portal will pass its own tid.
   */
  tenantId?: string | null;
}

type Status = 'idle' | 'submitting' | 'sent' | 'error';

export function LoginPage({ tenantId = null }: LoginPageProps = {}) {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const isLocalhost =
    typeof window !== 'undefined' &&
    /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(window.location.hostname);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) {
      setErrorMsg(t('admin.login.email_required'));
      setStatus('error');
      return;
    }
    setStatus('submitting');
    setErrorMsg(null);
    // Dev-port UX: vite (:5175) and uvicorn (:8000) differ, so ask the backend
    // to bake an absolute redirect on THIS origin into the magic link. The
    // server validates the redirect matches our `Origin` header (see
    // tests/auth/test_request_login.py::test_redirect_override_*).
    const redirect =
      typeof window !== 'undefined'
        ? `${window.location.origin}${tenantId ? `/t/${tenantId}/admin` : '/admin'}`
        : undefined;
    try {
      const resp = await fetch('/api/auth/request-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmed, tenant_id: tenantId, redirect }),
      });
      if (!resp.ok) {
        throw new Error(`request-login ${resp.status}`);
      }
      setStatus('sent');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      setStatus('error');
    }
  };

  const busy = status === 'submitting';

  return (
    <div
      data-testid="login-page"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background:
          'radial-gradient(ellipse at top, var(--indigo-50) 0%, var(--color-bg) 60%)',
        fontFamily: 'var(--font-sans)',
        padding: 16,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 360,
          padding: 28,
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-elevated)',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20 }}>{t('admin.login.title')}</h1>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 13, marginTop: 6 }}>
          {t('admin.login.subtitle')}
        </p>

        {status === 'sent' ? (
          <div
            data-testid="login-sent"
            role="status"
            style={{
              marginTop: 20,
              padding: 12,
              borderRadius: 'var(--radius-md)',
              background: 'var(--spring-50)',
              color: 'var(--spring-900)',
              fontSize: 13,
            }}
          >
            {t('admin.login.sent')}
            {isLocalhost ? (
              <div
                data-testid="login-dev-hint"
                style={{ marginTop: 6, color: 'var(--color-text-secondary)', fontSize: 12 }}
              >
                {t('admin.login.dev_hint')}
              </div>
            ) : null}
          </div>
        ) : (
          <form
            onSubmit={onSubmit}
            aria-busy={busy ? 'true' : 'false'}
            noValidate
            style={{ marginTop: 20 }}
          >
            <label
              htmlFor="login-email"
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--color-text)',
                marginBottom: 6,
              }}
            >
              {t('admin.login.email_label')}
            </label>
            <input
              id="login-email"
              name="email"
              type="email"
              required
              autoComplete="email"
              data-testid="login-email-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
              style={{
                width: '100%',
                padding: '8px 10px',
                fontSize: 14,
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                boxSizing: 'border-box',
              }}
            />

            {errorMsg ? (
              <div
                data-testid="login-error"
                role="alert"
                style={{
                  marginTop: 10,
                  color: 'var(--color-danger)',
                  fontSize: 12,
                }}
              >
                {errorMsg}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={busy}
              data-testid="login-submit"
              style={{
                marginTop: 16,
                width: '100%',
                padding: '9px 14px',
                border: '1px solid var(--color-primary)',
                borderRadius: 'var(--radius-sm)',
                background: busy ? 'var(--indigo-200)' : 'var(--color-primary)',
                color: '#fff',
                fontSize: 14,
                fontWeight: 600,
                cursor: busy ? 'wait' : 'pointer',
              }}
            >
              {busy ? t('admin.login.sending') : t('admin.login.send')}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
