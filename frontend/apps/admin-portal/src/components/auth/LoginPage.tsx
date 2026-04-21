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
import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';

const DEV_RECENT_KEY = 'autoservice.dev.recentPersonas';

function readRecentPersonas(): string[] {
  try {
    const raw = localStorage.getItem(DEV_RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === 'string')
      : [];
  } catch {
    return [];
  }
}

function pushRecentPersona(email: string): void {
  const prev = readRecentPersonas().filter((e) => e !== email);
  const next = [email, ...prev].slice(0, 5);
  try {
    localStorage.setItem(DEV_RECENT_KEY, JSON.stringify(next));
  } catch {
    // ignore quota / disabled storage
  }
}

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

interface DevMode {
  enabled: boolean;
  personas: string[];
  tenants: string[];
}

export function LoginPage({ tenantId = null }: LoginPageProps = {}) {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [devMode, setDevMode] = useState<DevMode>({
    enabled: false,
    personas: [],
    tenants: [],
  });
  const [devEmail, setDevEmail] = useState('');
  const [devTenantChoice, setDevTenantChoice] = useState<string>('');
  const [devTenantCustom, setDevTenantCustom] = useState('');
  const [devStatus, setDevStatus] = useState<
    'idle' | 'submitting' | 'error'
  >('idle');
  const [devError, setDevError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/auth/dev-mode')
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((data) => {
        if (cancelled) return;
        if (data && data.enabled) {
          setDevMode({
            enabled: true,
            personas: Array.isArray(data.personas) ? data.personas : [],
            tenants: Array.isArray(data.tenants) ? data.tenants : [],
          });
        }
      })
      .catch(() => {
        // Probe failure is non-fatal — just keep the dev panel hidden.
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const onDevSubmit = async () => {
    const trimmedEmail = devEmail.trim();
    if (!trimmedEmail) {
      setDevError('Persona email is required.');
      setDevStatus('error');
      return;
    }
    let tid: string | null;
    if (devTenantChoice === '') {
      tid = null;
    } else if (devTenantChoice === '__custom__') {
      const custom = devTenantCustom.trim();
      tid = custom ? custom : null;
    } else {
      tid = devTenantChoice;
    }
    setDevStatus('submitting');
    setDevError(null);
    try {
      const resp = await fetch('/api/auth/dev-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmedEmail, tenant_id: tid }),
      });
      if (resp.status === 404) {
        setDevError(
          'Dev mode is off on the server. Set AUTH_DEV_MODE=1 and restart.'
        );
        setDevStatus('error');
        return;
      }
      if (!resp.ok) {
        setDevError(`Dev login failed (${resp.status})`);
        setDevStatus('error');
        return;
      }
      const data = await resp.json();
      pushRecentPersona(trimmedEmail);
      if (typeof window !== 'undefined' && data && typeof data.redirect === 'string') {
        window.location.assign(data.redirect);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setDevError(msg);
      setDevStatus('error');
    }
  };

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

        {devMode.enabled ? (
          <div
            data-testid="dev-login-panel"
            style={{
              marginTop: 24,
              paddingTop: 16,
              borderTop: '1px dashed #d0d7de',
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: '#8c959f',
                textTransform: 'uppercase',
                letterSpacing: 0.6,
                marginBottom: 10,
              }}
            >
              Developer quick login
            </div>

            <label
              htmlFor="dev-login-email"
              style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}
            >
              Persona email
            </label>
            <input
              id="dev-login-email"
              list="dev-login-personas"
              type="email"
              data-testid="dev-login-email"
              value={devEmail}
              onChange={(e) => setDevEmail(e.target.value)}
              disabled={devStatus === 'submitting'}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 13,
                border: '1px solid #d0d7de',
                borderRadius: 6,
                boxSizing: 'border-box',
              }}
            />
            <datalist id="dev-login-personas">
              {(() => {
                const recent = readRecentPersonas();
                const merged: string[] = [];
                for (const p of [...recent, ...devMode.personas]) {
                  if (!merged.includes(p)) merged.push(p);
                }
                return merged.map((p) => <option key={p} value={p} />);
              })()}
            </datalist>

            <label
              htmlFor="dev-login-tenant-select"
              style={{ display: 'block', fontSize: 12, fontWeight: 600, marginTop: 10, marginBottom: 4 }}
            >
              Tenant scope
            </label>
            <select
              id="dev-login-tenant-select"
              data-testid="dev-login-tenant-select"
              value={devTenantChoice}
              onChange={(e) => setDevTenantChoice(e.target.value)}
              disabled={devStatus === 'submitting'}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 13,
                border: '1px solid #d0d7de',
                borderRadius: 6,
                boxSizing: 'border-box',
                background: '#ffffff',
              }}
            >
              <option value="">None (tier-0 master)</option>
              {devMode.tenants.map((tid) => (
                <option key={tid} value={tid}>{tid}</option>
              ))}
              <option value="__custom__">Custom…</option>
            </select>

            {devTenantChoice === '__custom__' ? (
              <input
                data-testid="dev-login-tenant-custom"
                type="text"
                placeholder="tenant_id"
                value={devTenantCustom}
                onChange={(e) => setDevTenantCustom(e.target.value)}
                disabled={devStatus === 'submitting'}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  fontSize: 13,
                  border: '1px solid #d0d7de',
                  borderRadius: 6,
                  boxSizing: 'border-box',
                  marginTop: 6,
                }}
              />
            ) : null}

            {devError ? (
              <div
                data-testid="dev-login-error"
                role="alert"
                style={{ marginTop: 10, color: '#cf222e', fontSize: 12 }}
              >
                {devError}
              </div>
            ) : null}

            <button
              type="button"
              data-testid="dev-login-submit"
              disabled={devStatus === 'submitting'}
              onClick={onDevSubmit}
              style={{
                marginTop: 12,
                width: '100%',
                padding: '8px 12px',
                border: '1px solid #6639ba',
                borderRadius: 6,
                background: devStatus === 'submitting' ? '#c5b0e5' : '#6639ba',
                color: '#ffffff',
                fontSize: 13,
                fontWeight: 600,
                cursor: devStatus === 'submitting' ? 'wait' : 'pointer',
              }}
            >
              {devStatus === 'submitting' ? 'Signing in…' : 'Dev login →'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
