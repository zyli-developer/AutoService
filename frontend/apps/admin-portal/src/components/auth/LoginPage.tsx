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
      setErrorMsg('Please enter your admin email address.');
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
          'radial-gradient(ellipse at top, #eff3fb 0%, #ffffff 60%)',
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        padding: 16,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 360,
          padding: 28,
          background: '#ffffff',
          border: '1px solid #d0d7de',
          borderRadius: 12,
          boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20 }}>Sign in to AutoService</h1>
        <p style={{ color: '#57606a', fontSize: 13, marginTop: 6 }}>
          We&apos;ll email you a magic link. No password needed.
        </p>

        {status === 'sent' ? (
          <div
            data-testid="login-sent"
            role="status"
            style={{
              marginTop: 20,
              padding: 12,
              borderRadius: 8,
              background: '#dafbe1',
              color: '#116329',
              fontSize: 13,
            }}
          >
            Check your email for a magic link.
            {isLocalhost ? (
              <div
                data-testid="login-dev-hint"
                style={{ marginTop: 6, color: '#57606a', fontSize: 12 }}
              >
                Dev mode: tail{' '}
                <code>.autoservice/logs/auth-devmail.jsonl</code> to
                retrieve the link.
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
                color: '#24292f',
                marginBottom: 6,
              }}
            >
              Admin email
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
                border: '1px solid #d0d7de',
                borderRadius: 6,
                boxSizing: 'border-box',
              }}
            />

            {errorMsg ? (
              <div
                data-testid="login-error"
                role="alert"
                style={{
                  marginTop: 10,
                  color: '#cf222e',
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
                border: '1px solid #0969da',
                borderRadius: 6,
                background: busy ? '#97c2ff' : '#0969da',
                color: '#ffffff',
                fontSize: 14,
                fontWeight: 600,
                cursor: busy ? 'wait' : 'pointer',
              }}
            >
              {busy ? 'Sending…' : 'Send magic link'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
