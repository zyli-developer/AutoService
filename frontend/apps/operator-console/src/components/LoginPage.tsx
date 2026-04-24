import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

/**
 * Dev-mode login form.
 *
 * Calls `POST /api/auth/operator/dev-login` (AUTH_DEV_MODE-gated on the
 * backend) which upserts an operators row and sets the `operator_session`
 * cookie — the same cookie that `/ws/operator` strict-validates after
 * M3 T1S.3.
 *
 * In production (AUTH_DEV_MODE unset) the endpoint returns 404 and this
 * form surfaces a disabled-mode hint pending the magic-link flow
 * rewire (see the M3 frontend login-wire carry-over task).
 */
export function LoginPage() {
  const { t } = useTranslation();
  const login = useOperatorStore((s) => s.login);
  const [email, setEmail] = useState('');
  const [tenantId, setTenantId] = useState('');
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
        <form onSubmit={handleSubmit}>
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
      </div>
    </div>
  );
}
