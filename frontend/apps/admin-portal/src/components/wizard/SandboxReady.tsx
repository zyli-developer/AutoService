/**
 * T1F.7 · Step 4 SandboxReady — sandbox overview + 一键对外 publish action.
 *
 * Wires the Step 4 "go live" button to POST /api/onboard/publish:
 *   - 200 → show tarball + runbook + archive paths
 *   - 409 → gate blocked, render blocking_reasons list
 *   - other → generic error surface
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §6
 */
import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

interface PublishResult {
  status: string;
  tenant_id: string;
  artifact?: string;
  artifact_sha256?: string;
  runbook?: string;
  record?: string;
  archived_to?: string;
  gate?: unknown;
}

interface PublishBlocked {
  error?: string;
  tenant_id?: string;
  status?: string;
  blocking_reasons?: string[];
  gate?: unknown;
}

// Use raw fetch rather than the shared api helper so we can branch on 409
// (gate blocked) without losing the JSON body.
const API_BASE =
  (import.meta as unknown as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ??
  '';

export function SandboxReady() {
  const { t } = useTranslation();
  // Prefer the tenant_id that /api/onboard/upload actually created (the one
  // that has a real sandbox dir on disk) over the login-time tenantId.
  // See WizardTab comment for the same precedence rule.
  const generationResult = useAdminStore((s) => s.generationResult);
  const loginTenantId = useAdminStore((s) => s.tenantId);
  const tenantId = generationResult?.tenantId || loginTenantId || 'default';

  const [publishing, setPublishing] = useState(false);
  const [result, setResult] = useState<PublishResult | null>(null);
  const [blocked, setBlocked] = useState<PublishBlocked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signerEmail, setSignerEmail] = useState('');

  const handlePublish = async (opts: { override?: boolean; signer?: string } = {}) => {
    setPublishing(true);
    setError(null);
    if (!opts.override) setBlocked(null);   // keep blocked panel visible during override attempt
    try {
      const body: Record<string, unknown> = { tenant_id: tenantId };
      if (opts.override && opts.signer) {
        body.override = true;
        body.signer = opts.signer;
      }
      const res = await fetch(`${API_BASE}/api/onboard/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (res.status === 409) {
        const data = (await res.json().catch(() => ({}))) as PublishBlocked;
        setBlocked(data);
        return;
      }

      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        setError(data.error || `HTTP ${res.status}`);
        return;
      }

      const data = (await res.json()) as PublishResult;
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  };

  // Extract blocking reasons list from the 409 payload. The gate detail is
  // nested either at top level (status=blocked) or under result.gate depending
  // on publish.py's output shape.
  const blockingReasons: string[] = (() => {
    if (!blocked) return [];
    if (Array.isArray(blocked.blocking_reasons)) return blocked.blocking_reasons;
    const gate = blocked.gate as { blocking_reasons?: unknown } | undefined;
    if (gate && Array.isArray(gate.blocking_reasons))
      return gate.blocking_reasons as string[];
    return [];
  })();

  return (
    <div data-testid="sandbox-ready">
      <div className="cs-card hl">
        <div className="cs-ct">🎉 {t('admin.wizard.sandbox.title')}</div>
        <div className="cs-row">
          <span>{t('admin.wizard.sandbox.url')}</span>
          <span
            data-testid="sandbox-url"
            style={{
              color: 'var(--m600)',
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
            }}
          >
            {tenantId}.sandbox.onesync
          </span>
        </div>
        <div className="cs-row">
          <span>{t('admin.wizard.sandbox.team')}</span>
          <span style={{ color: 'var(--color-text-ink)' }}>
            {t('admin.wizard.sandbox.team_count', { count: 5 })}
          </span>
        </div>
        <div className="cs-row">
          <span>{t('admin.wizard.sandbox.public')}</span>
          <span style={{ color: 'var(--l700)', fontWeight: 700 }}>
            {t('admin.wizard.sandbox.pending_merchant')}
          </span>
        </div>

        {!result && (
          <div style={{ marginTop: 10 }}>
            <button
              className="cs-btn ok"
              data-testid="btn-publish"
              onClick={() => handlePublish()}
              disabled={publishing}
            >
              {publishing
                ? t('admin.wizard.sandbox.publishing')
                : t('admin.wizard.sandbox.publish')}
            </button>
            <div className="cs-pg ok" style={{ marginTop: 8 }}>
              {t('admin.wizard.sandbox.one_click_live')}
            </div>
          </div>
        )}

        {result && (
          <div data-testid="publish-result" style={{ marginTop: 12 }}>
            <div className="cs-pg ok">
              {t('admin.wizard.sandbox.publish_success')}
            </div>
            {result.artifact && (
              <div className="cs-row">
                <span>{t('admin.wizard.sandbox.artifact')}</span>
                <span
                  data-testid="result-artifact"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                >
                  {result.artifact}
                </span>
              </div>
            )}
            {result.runbook && (
              <div className="cs-row">
                <span>{t('admin.wizard.sandbox.runbook')}</span>
                <span
                  data-testid="result-runbook"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                >
                  {result.runbook}
                </span>
              </div>
            )}
            {result.archived_to && (
              <div className="cs-row">
                <span>{t('admin.wizard.sandbox.archived')}</span>
                <span
                  data-testid="result-archived"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                >
                  {result.archived_to}
                </span>
              </div>
            )}
          </div>
        )}

        {blocked && !result && (
          <div
            data-testid="publish-blocked"
            style={{ marginTop: 12, padding: 10, background: 'var(--l50)' }}
          >
            <div style={{ fontWeight: 700, color: 'var(--l800)' }}>
              ⚠ {t('admin.wizard.sandbox.blocked_title')}
            </div>
            <div style={{ fontSize: 11, color: 'var(--charcoal)', marginTop: 4 }}>
              {t('admin.wizard.sandbox.blocked_hint')}
            </div>
            {blockingReasons.length > 0 && (
              <ul
                data-testid="blocking-reasons"
                style={{ margin: '8px 0 0 20px', fontSize: 12 }}
              >
                {blockingReasons.map((reason, i) => (
                  <li key={i} data-testid={`blocking-reason-${i}`}>
                    {reason}
                  </li>
                ))}
              </ul>
            )}

            {/* Override form — platform admin signs off to bypass gate (M1). */}
            <div
              data-testid="publish-override"
              style={{
                marginTop: 12,
                paddingTop: 10,
                borderTop: '1px solid var(--oat)',
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600 }}>
                {t('admin.wizard.sandbox.override_title')}
              </div>
              <div
                style={{ fontSize: 11, color: 'var(--silver)', marginTop: 2 }}
              >
                {t('admin.wizard.sandbox.override_hint')}
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: 8,
                  marginTop: 8,
                  alignItems: 'center',
                }}
              >
                <input
                  data-testid="override-signer-input"
                  type="email"
                  value={signerEmail}
                  onChange={(e) => setSignerEmail(e.target.value)}
                  placeholder={t(
                    'admin.wizard.sandbox.override_email_placeholder',
                  )}
                  style={{
                    flex: 1,
                    padding: '6px 10px',
                    border: '1px solid var(--oat)',
                    borderRadius: 6,
                    fontSize: 12,
                    fontFamily: 'var(--font-sans)',
                    outline: 'none',
                  }}
                />
                <button
                  className="cs-btn"
                  data-testid="btn-override-publish"
                  onClick={() =>
                    handlePublish({
                      override: true,
                      signer: signerEmail.trim(),
                    })
                  }
                  disabled={
                    publishing ||
                    !signerEmail.trim() ||
                    !signerEmail.includes('@')
                  }
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {publishing
                    ? t('admin.wizard.sandbox.publishing')
                    : t('admin.wizard.sandbox.override_confirm')}
                </button>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div
            data-testid="publish-error"
            style={{ marginTop: 12, color: 'var(--l800)' }}
          >
            {t('admin.wizard.sandbox.publish_failed', { error })}
          </div>
        )}
      </div>
    </div>
  );
}
