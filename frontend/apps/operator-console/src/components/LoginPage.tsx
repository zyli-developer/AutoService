import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useTenantId } from '@autoservice/shared';
import { useOperatorStore } from '../store/operatorStore';

/**
 * Operator login form.
 *
 * Two paths:
 * 1. **Password login** (primary, public-deploy default) — calls
 *    `POST /api/auth/operator/password-login`. Reads
 *    `.autoservice/operator_passwords.json`; returns 404 when the file
 *    is missing (feature disabled). On 200 the cookie is set and the
 *    handler-supplied redirect is followed.
 * 2. **Dev-login** (collapsed below, AUTH_DEV_MODE-gated) — calls
 *    `POST /api/auth/operator/dev-login`, retained for local-dev so a
 *    cookie can be minted without provisioning a password file.
 *
 * Both paths set the same `operator_session` cookie that
 * `/ws/operator` strict-validates after M3 T1S.3.
 */
export function LoginPage() {
  const { t } = useTranslation();
  const login = useOperatorStore((s) => s.login);
  // Pre-fill tenant from URL (path /tenant/:id/* or query ?tenant=...).
  // Operators landing on /console/?tenant=cinnox don't have to retype it.
  const urlTenant = useTenantId();

  // ── Password login ──────────────────────────────────────────────────
  const [pwEmail, setPwEmail] = useState('');
  const [pwPassword, setPwPassword] = useState('');
  const [pwTenant, setPwTenant] = useState(urlTenant ?? '');
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);

  const canSubmitPw =
    pwEmail.trim().length > 0 &&
    pwPassword.length > 0 &&
    pwTenant.trim().length > 0 &&
    !pwBusy;

  const handlePasswordSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!canSubmitPw) return;
    setPwBusy(true);
    setPwError(null);
    try {
      const r = await fetch('/api/auth/operator/password-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          email: pwEmail.trim(),
          password: pwPassword,
          tenant_id: pwTenant.trim(),
        }),
      });
      if (r.status === 404) {
        setPwError(t('operator.login.error_password_disabled'));
        return;
      }
      if (r.status === 429) {
        setPwError(t('operator.login.error_too_many_attempts'));
        return;
      }
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const body = await r.json();
          if (typeof body?.error === 'string') msg = body.error;
        } catch {
          /* ignore parse errors */
        }
        setPwError(t('operator.login.error_generic', { error: msg }));
        return;
      }
      const body = (await r.json()) as { operator_id: string };
      login(body.operator_id, '');
    } catch (err) {
      setPwError(t('operator.login.error_generic', { error: String(err) }));
    } finally {
      setPwBusy(false);
    }
  };

  // ── Dev login (AUTH_DEV_MODE) ───────────────────────────────────────
  const [email, setEmail] = useState('');
  const [tenantId, setTenantId] = useState(urlTenant ?? '');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = email.trim().length > 0 && tenantId.trim().length > 0 && !submitting;

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch('/api/auth/operator/dev-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          email: email.trim(),
          tenant_id: tenantId.trim(),
        }),
      });
      if (r.status === 404) {
        setError(t('operator.login.error_dev_disabled'));
        return;
      }
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const body = await r.json();
          if (typeof body?.error === 'string') msg = body.error;
        } catch {
          /* ignore parse errors */
        }
        setError(t('operator.login.error_generic', { error: msg }));
        return;
      }
      const body = (await r.json()) as { operator_id: string };
      // Cookie is now set by the browser. Flip store → WorkspacePage mounts,
      // useOperatorWS opens the WS with the freshly-minted cookie.
      login(body.operator_id, '');
    } catch (err) {
      setError(t('operator.login.error_generic', { error: String(err) }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="im-login">
      <div className="im-login-card">
        <h2>{t('operator.login.title')}</h2>

        {/* Password login — production path */}
        <form onSubmit={handlePasswordSubmit}>
          <input
            data-testid="pw-input-email"
            type="email"
            autoComplete="username"
            placeholder={t('operator.login.email')}
            value={pwEmail}
            onChange={(e) => setPwEmail(e.target.value)}
          />
          <input
            data-testid="pw-input-password"
            type="password"
            autoComplete="current-password"
            placeholder={t('operator.login.password')}
            value={pwPassword}
            onChange={(e) => setPwPassword(e.target.value)}
          />
          <input
            data-testid="pw-input-tenant-id"
            placeholder={t('operator.login.tenant_id')}
            value={pwTenant}
            onChange={(e) => setPwTenant(e.target.value)}
          />
          <button
            type="submit"
            disabled={!canSubmitPw}
            data-testid="pw-btn-login"
          >
            {pwBusy ? t('common.loading') : t('common.login')}
          </button>
          {pwError && (
            <div className="im-login-error" data-testid="pw-login-error">
              {pwError}
            </div>
          )}
        </form>

        {/* Dev login — AUTH_DEV_MODE only; 404 outside dev */}
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, opacity: 0.7 }}>
            {t('operator.login.dev_login_toggle')}
          </summary>
          <form onSubmit={handleSubmit} style={{ marginTop: 8 }}>
            <input
              data-testid="input-email"
              type="email"
              autoComplete="username"
              placeholder={t('operator.login.email')}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              data-testid="input-tenant-id"
              placeholder={t('operator.login.tenant_id')}
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
            />
            <button
              type="submit"
              disabled={!canSubmit}
              data-testid="btn-login"
            >
              {submitting ? t('common.loading') : t('common.login')}
            </button>
            {error && (
              <div className="im-login-error" data-testid="login-error">
                {error}
              </div>
            )}
          </form>
        </details>
      </div>
    </div>
  );
}
