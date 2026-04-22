import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../store/adminStore';
import { fetchJSON, postJSON } from '../api';
import { CanaryPanel } from './dream/canary-panel';

interface DreamStatus {
  tenant_id: string;
  running: boolean;
  reason_code: string;
  last_run_summary: {
    run_id: string;
    started_at: string;
    ended_at: string | null;
    status: string;
    proposals_emitted: number | null;
    tool_calls: number | null;
  } | null;
  next_eligible_at: string | null;
}

interface DreamProposal {
  id: string;
  created_at: string;
  category: string;
  title: string;
  priority: string;
  status: string;
  suggestion?: string;
  source_conversations?: string[];
}

interface DreamRun {
  id: string;
  tenant_id: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  tokens_in: number | null;
  tokens_out: number | null;
  error: string | null;
}

interface TenantEntry {
  tenant_id: string;
  name?: string;
  status?: string;
}

const REASON_CODE_STYLE: Record<string, { label: string; bg: string; color: string }> = {
  idle: { label: 'idle', bg: 'var(--color-accent-subtle)', color: 'var(--color-accent-text)' },
  scheduled_hit: { label: 'scheduled_hit', bg: 'var(--color-accent-subtle)', color: 'var(--color-accent-text)' },
  already_running: { label: 'running', bg: 'var(--color-premium-subtle)', color: 'var(--color-premium-text)' },
  cool_down_active: { label: 'cool_down', bg: 'var(--color-premium-subtle)', color: 'var(--color-premium-text)' },
  not_idle: { label: 'not_idle', bg: 'var(--color-premium-subtle)', color: 'var(--color-premium-text)' },
  scheduled_miss: { label: 'scheduled_miss', bg: 'var(--color-premium-subtle)', color: 'var(--color-premium-text)' },
  never_active: { label: 'never_active', bg: 'var(--color-bg-surface-tinted)', color: 'var(--color-text-muted)' },
  manual_only: { label: 'manual_only', bg: 'var(--color-bg-surface-tinted)', color: 'var(--color-text-muted)' },
  coverage_disabled: { label: 'disabled', bg: 'var(--color-bg-surface-tinted)', color: 'var(--color-text-muted)' },
  insufficient_signal: { label: 'insufficient_signal', bg: 'var(--color-bg-surface-tinted)', color: 'var(--color-text-muted)' },
  unknown_trigger: { label: 'unknown', bg: 'var(--color-danger-subtle)', color: 'var(--color-danger-text)' },
};

const STATUS_COLOR: Record<string, string> = {
  draft: 'var(--color-text-muted)',
  accepted: 'var(--color-primary)',
  applied: 'var(--color-accent-text)',
  rejected: 'var(--color-danger)',
  blocked: 'var(--color-premium-text)',
};

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString();
  } catch {
    return ts;
  }
}

const MASTER_TENANT_ID = '_master';

export function DreamTab() {
  const { t } = useTranslation();
  const storeTenantId = useAdminStore((s) => s.tenantId);

  const [tenants, setTenants] = useState<TenantEntry[]>([]);
  const [selectedTenant, setSelectedTenant] = useState<string>(MASTER_TENANT_ID);
  const tenantId = selectedTenant;

  const [status, setStatus] = useState<DreamStatus | null>(null);
  const [proposals, setProposals] = useState<DreamProposal[]>([]);
  const [runs, setRuns] = useState<DreamRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Load the tenant list once on mount.  Prefer the store's tenant if it
  // matches a real entry; otherwise fall back to _master so the trigger
  // endpoint (which validates tenant existence) doesn't 404.
  useEffect(() => {
    fetchJSON<TenantEntry[]>('/api/master/tenants')
      .then((list) => {
        const arr = Array.isArray(list) ? list : [];
        // Always include _master so platform dream is selectable even
        // if the backend list omits it.
        const seen = new Set(arr.map((t) => t.tenant_id));
        const merged: TenantEntry[] = [...arr];
        if (!seen.has(MASTER_TENANT_ID)) {
          merged.unshift({ tenant_id: MASTER_TENANT_ID, name: 'Platform master' });
        }
        setTenants(merged);
        // Seed selection: prefer store tenant if valid, else _master.
        if (storeTenantId && merged.some((e) => e.tenant_id === storeTenantId)) {
          setSelectedTenant(storeTenantId);
        } else {
          setSelectedTenant(MASTER_TENANT_ID);
        }
      })
      .catch(() => {
        setTenants([{ tenant_id: MASTER_TENANT_ID, name: 'Platform master' }]);
        setSelectedTenant(MASTER_TENANT_ID);
      });
  }, [storeTenantId]);

  const load = useCallback(() => {
    if (!tenantId) return;
    setLoading(true);
    setErrorMsg(null);
    Promise.all([
      fetchJSON<DreamStatus>(`/api/dream/status?tenant_id=${encodeURIComponent(tenantId)}`)
        .then(setStatus)
        .catch(() => setStatus(null)),
      fetchJSON<DreamProposal[]>(`/api/proposals`)
        .then((all) => {
          const arr = Array.isArray(all) ? all : [];
          setProposals(arr.filter((p) => !p.status || p.status !== 'rejected'));
        })
        .catch(() => setProposals([])),
      fetchJSON<{ tenant_id: string; runs: DreamRun[] }>(
        `/api/dream/runs?tenant_id=${encodeURIComponent(tenantId)}&limit=10`,
      )
        .then((r) => setRuns(Array.isArray(r?.runs) ? r.runs : []))
        .catch(() => setRuns([])),
    ]).finally(() => setLoading(false));
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleTrigger = async () => {
    if (!tenantId || triggering) return;
    setTriggering(true);
    setErrorMsg(null);
    try {
      await postJSON<unknown>('/api/dream/trigger', { tenant_id: tenantId });
      setTimeout(load, 800);
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      setErrorMsg(`${t('admin.dream.error.trigger_failed')} (${detail})`);
    } finally {
      setTriggering(false);
    }
  };

  const reasonBadge = status
    ? REASON_CODE_STYLE[status.reason_code] || {
        label: status.reason_code,
        bg: 'var(--color-bg-surface-tinted)',
        color: 'var(--color-text-muted)',
      }
    : null;

  const pending = proposals.filter((p) => p.status === 'draft' || p.status === 'accepted');
  const recentApplied = proposals.filter((p) => p.status === 'applied').slice(0, 5);
  const selectedProposal =
    pending.find((p) => p.id === selectedProposalId) ?? null;

  return (
    <div data-testid="tab-dream">
      {/* ── Status Card ───────────────────────────────────────────── */}
      <section className="cs-card" data-testid="dream-status-card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 12 }}>
          <div>
            <div className="cs-ct" style={{ marginBottom: 6 }}>
              {t('admin.dream.status.title')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <label htmlFor="dream-tenant-select">{t('admin.dream.status.tenant_label')}:</label>
              <select
                id="dream-tenant-select"
                data-testid="dream-tenant-select"
                value={selectedTenant}
                onChange={(e) => setSelectedTenant(e.target.value)}
                style={{
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-sm, 4px)',
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-bg-surface)',
                  color: 'var(--color-text)',
                  fontSize: 12,
                  fontFamily: 'var(--font-mono)',
                  minWidth: 180,
                }}
              >
                {tenants.map((entry) => (
                  <option key={entry.tenant_id} value={entry.tenant_id}>
                    {entry.tenant_id}
                    {entry.name && entry.name !== entry.tenant_id ? ` · ${entry.name}` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            className="cs-btn ok"
            onClick={handleTrigger}
            disabled={triggering || !tenantId}
            data-testid="dream-trigger-btn"
            style={{ opacity: triggering ? 0.6 : 1 }}
          >
            {triggering ? t('admin.dream.trigger.running') : t('admin.dream.trigger.cta')}
          </button>
        </div>

        {loading && !status && (
          <div className="im-empty" data-testid="dream-status-loading">
            {t('common.loading')}
          </div>
        )}

        {status && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '0.05em' }}>
                {t('admin.dream.status.running_label')}
              </div>
              <div style={{ fontSize: 14, fontWeight: 500 }} data-testid="dream-status-running">
                {status.running ? t('admin.dream.status.running_yes') : t('admin.dream.status.running_no')}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '0.05em' }}>
                {t('admin.dream.status.reason_label')}
              </div>
              {reasonBadge && (
                <span
                  data-testid="dream-reason-code"
                  style={{
                    display: 'inline-block',
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-sm, 4px)',
                    background: reasonBadge.bg,
                    color: reasonBadge.color,
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  {reasonBadge.label}
                </span>
              )}
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '0.05em' }}>
                {t('admin.dream.status.last_run_label')}
              </div>
              <div style={{ fontSize: 13 }} data-testid="dream-last-run">
                {status.last_run_summary ? (
                  <>
                    <div style={{ fontWeight: 500 }}>{status.last_run_summary.status}</div>
                    <div style={{ color: 'var(--color-text-secondary)', fontSize: 11 }}>
                      {formatTs(status.last_run_summary.started_at)}
                    </div>
                  </>
                ) : (
                  <span style={{ color: 'var(--color-text-muted)' }}>—</span>
                )}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '0.05em' }}>
                {t('admin.dream.status.next_eligible_label')}
              </div>
              <div style={{ fontSize: 13 }}>{formatTs(status.next_eligible_at)}</div>
            </div>
          </div>
        )}
      </section>

      {errorMsg && (
        <div
          role="alert"
          data-testid="dream-error"
          className="adm-chat-widget-alert"
          style={{ marginBottom: 16 }}
        >
          ⚠ {errorMsg}
        </div>
      )}

      {/* ── Canary Panel (mounts when a pending proposal is selected) ─ */}
      {/* When an action transitions the proposal out of pending (applied/
          rejected), `pending.find(...)` returns undefined on the next
          render and `selectedProposal` becomes null — the panel unmounts
          naturally. No explicit `setSelectedProposalId(null)` needed. */}
      {selectedProposal && (
        <CanaryPanel
          key={selectedProposal.id}
          proposal={{
            id: selectedProposal.id,
            title: selectedProposal.title,
            category: selectedProposal.category,
            status: selectedProposal.status,
            suggestion: selectedProposal.suggestion,
          }}
          onReload={load}
        />
      )}

      {/* ── Pending Proposals ─────────────────────────────────────── */}
      <section data-testid="dream-proposals-section" style={{ marginBottom: 24 }}>
        <div className="cs-ct" style={{ marginBottom: 12 }}>
          {t('admin.dream.proposals.title')}
          <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontWeight: 400 }}>
            ({pending.length})
          </span>
        </div>
        {pending.length === 0 ? (
          <div className="im-empty">{t('admin.dream.proposals.empty')}</div>
        ) : (
          <table
            data-testid="dream-proposals-table"
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md, 6px)',
              overflow: 'hidden',
            }}
          >
            <thead>
              <tr style={{ background: 'var(--color-bg-surface-tinted)', borderBottom: '1px solid var(--color-border)' }}>
                <th style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.created')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.category')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.title')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.status')}</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p) => {
                const isSelected = p.id === selectedProposalId;
                return (
                  <tr
                    key={p.id}
                    data-testid={`dream-proposal-row-${p.id}`}
                    onClick={() =>
                      setSelectedProposalId(isSelected ? null : p.id)
                    }
                    style={{
                      borderBottom: '1px solid var(--color-border-subtle, var(--color-border))',
                      cursor: 'pointer',
                      background: isSelected
                        ? 'var(--color-accent-subtle, var(--color-bg-surface-tinted))'
                        : undefined,
                    }}
                  >
                    <td style={{ padding: '8px 10px', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatTs(p.created_at)}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <code style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>{p.category}</code>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ fontWeight: 500 }}>{p.title}</div>
                      {p.suggestion && (
                        <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginTop: 2 }}>
                          {p.suggestion.slice(0, 120)}
                          {p.suggestion.length > 120 ? '…' : ''}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span
                        style={{
                          color: STATUS_COLOR[p.status] || 'var(--color-text-secondary)',
                          fontWeight: 500,
                        }}
                      >
                        {p.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Recently Applied ──────────────────────────────────────── */}
      {recentApplied.length > 0 && (
        <section data-testid="dream-applied-section" style={{ marginBottom: 24 }}>
          <div className="cs-ct" style={{ marginBottom: 12 }}>
            {t('admin.dream.applied.title')}
          </div>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {recentApplied.map((p) => (
              <li key={p.id} className="im-block highlight" style={{ marginTop: 0 }}>
                <div className="im-block-title">{p.title}</div>
                <div className="im-block-meta">
                  <code style={{ fontFamily: 'var(--font-mono)' }}>{p.category}</code> · {formatTs(p.created_at)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ── Recent Runs ───────────────────────────────────────────── */}
      <section data-testid="dream-runs-section">
        <div className="cs-ct" style={{ marginBottom: 12 }}>
          {t('admin.dream.runs.title')}
        </div>
        {runs.length === 0 ? (
          <div className="im-empty">{t('admin.dream.runs.empty')}</div>
        ) : (
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 12,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md, 6px)',
              overflow: 'hidden',
            }}
          >
            <thead>
              <tr style={{ background: 'var(--color-bg-surface-tinted)', borderBottom: '1px solid var(--color-border)' }}>
                <th style={{ textAlign: 'left', padding: '6px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.started')}</th>
                <th style={{ textAlign: 'left', padding: '6px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.status')}</th>
                <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: 500, color: 'var(--color-text-secondary)' }}>{t('admin.dream.col.tokens')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--color-border-subtle, var(--color-border))' }}>
                  <td style={{ padding: '6px 10px', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
                    {formatTs(r.started_at)}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    <span style={{ color: STATUS_COLOR[r.status] || 'var(--color-text-secondary)', fontWeight: 500 }}>
                      {r.status}
                    </span>
                    {r.error && (
                      <div style={{ fontSize: 10, color: 'var(--color-danger)' }}>{r.error.slice(0, 80)}</div>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--color-text-secondary)' }}>
                    {r.tokens_in ?? 0} / {r.tokens_out ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
