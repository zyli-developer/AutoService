import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../store/adminStore';
import { fetchJSON, postJSON } from '../api';

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

const REASON_CODE_STYLE: Record<string, { label: string; bg: string; color: string }> = {
  idle: { label: 'idle', bg: '#e6f4ea', color: '#137333' },
  scheduled_hit: { label: 'scheduled_hit', bg: '#e6f4ea', color: '#137333' },
  already_running: { label: 'running', bg: '#fef7e0', color: '#b06000' },
  cool_down_active: { label: 'cool_down', bg: '#fef7e0', color: '#b06000' },
  not_idle: { label: 'not_idle', bg: '#fef7e0', color: '#b06000' },
  scheduled_miss: { label: 'scheduled_miss', bg: '#fef7e0', color: '#b06000' },
  never_active: { label: 'never_active', bg: '#f1f3f4', color: '#5f6368' },
  manual_only: { label: 'manual_only', bg: '#f1f3f4', color: '#5f6368' },
  coverage_disabled: { label: 'disabled', bg: '#f1f3f4', color: '#5f6368' },
  insufficient_signal: { label: 'insufficient_signal', bg: '#f1f3f4', color: '#5f6368' },
  unknown_trigger: { label: 'unknown', bg: '#fce8e6', color: '#c5221f' },
};

const STATUS_COLOR: Record<string, string> = {
  draft: '#5f6368',
  accepted: '#1a73e8',
  applied: '#137333',
  rejected: '#c5221f',
  blocked: '#b06000',
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

export function DreamTab() {
  const { t } = useTranslation();
  const storeTenantId = useAdminStore((s) => s.tenantId);
  const tenantId = storeTenantId ?? '_master';

  const [status, setStatus] = useState<DreamStatus | null>(null);
  const [proposals, setProposals] = useState<DreamProposal[]>([]);
  const [runs, setRuns] = useState<DreamRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!tenantId) return;
    setLoading(true);
    setErrorMsg(null);
    Promise.all([
      fetchJSON<DreamStatus>(`/api/dream/status?tenant_id=${encodeURIComponent(tenantId)}`)
        .then(setStatus)
        .catch(() => setStatus(null)),
      fetchJSON<DreamProposal[]>(`/api/proposals`)
        .then((all) => setProposals(all.filter((p) => !p.status || p.status !== 'rejected')))
        .catch(() => setProposals([])),
      fetchJSON<DreamRun[]>(`/api/dream/runs?tenant_id=${encodeURIComponent(tenantId)}&limit=10`)
        .then(setRuns)
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
      setErrorMsg(t('admin.dream.error.trigger_failed'));
    } finally {
      setTriggering(false);
    }
  };

  const handleApply = async (proposalId: string) => {
    setApplyingId(proposalId);
    setErrorMsg(null);
    try {
      await postJSON<unknown>(`/api/admin/proposals/${proposalId}/apply`);
      load();
    } catch (e) {
      setErrorMsg(t('admin.dream.error.apply_failed', { id: proposalId }));
    } finally {
      setApplyingId(null);
    }
  };

  const reasonBadge = status
    ? REASON_CODE_STYLE[status.reason_code] || {
        label: status.reason_code,
        bg: '#f1f3f4',
        color: '#5f6368',
      }
    : null;

  const pending = proposals.filter((p) => p.status === 'draft' || p.status === 'accepted');
  const recentApplied = proposals.filter((p) => p.status === 'applied').slice(0, 5);

  return (
    <div data-testid="tab-dream" style={{ padding: '0 4px' }}>
      {/* ── Status Card ───────────────────────────────────────────── */}
      <section
        data-testid="dream-status-card"
        style={{
          border: '1px solid var(--l500)',
          borderRadius: 8,
          padding: 16,
          marginBottom: 20,
          background: 'var(--m50)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
              {t('admin.dream.status.title')}
            </h3>
            <div style={{ fontSize: 12, color: 'var(--m600)', marginTop: 4 }}>
              {t('admin.dream.status.tenant_label')}: <code>{tenantId}</code>
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
              <div style={{ fontSize: 11, color: 'var(--m600)', textTransform: 'uppercase', marginBottom: 4 }}>
                {t('admin.dream.status.running_label')}
              </div>
              <div style={{ fontSize: 14, fontWeight: 500 }} data-testid="dream-status-running">
                {status.running ? t('admin.dream.status.running_yes') : t('admin.dream.status.running_no')}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--m600)', textTransform: 'uppercase', marginBottom: 4 }}>
                {t('admin.dream.status.reason_label')}
              </div>
              {reasonBadge && (
                <span
                  data-testid="dream-reason-code"
                  style={{
                    display: 'inline-block',
                    padding: '2px 8px',
                    borderRadius: 4,
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
              <div style={{ fontSize: 11, color: 'var(--m600)', textTransform: 'uppercase', marginBottom: 4 }}>
                {t('admin.dream.status.last_run_label')}
              </div>
              <div style={{ fontSize: 13 }} data-testid="dream-last-run">
                {status.last_run_summary ? (
                  <>
                    <div style={{ fontWeight: 500 }}>{status.last_run_summary.status}</div>
                    <div style={{ color: 'var(--m600)', fontSize: 11 }}>
                      {formatTs(status.last_run_summary.started_at)}
                    </div>
                  </>
                ) : (
                  <span style={{ color: 'var(--m500)' }}>—</span>
                )}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--m600)', textTransform: 'uppercase', marginBottom: 4 }}>
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
          style={{
            padding: 10,
            marginBottom: 16,
            background: '#fce8e6',
            color: '#c5221f',
            borderRadius: 6,
            fontSize: 13,
          }}
        >
          {errorMsg}
        </div>
      )}

      {/* ── Pending Proposals ─────────────────────────────────────── */}
      <section data-testid="dream-proposals-section" style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px 0' }}>
          {t('admin.dream.proposals.title')}
          <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--m600)' }}>
            ({pending.length})
          </span>
        </h3>
        {pending.length === 0 ? (
          <div className="im-empty">{t('admin.dream.proposals.empty')}</div>
        ) : (
          <table
            data-testid="dream-proposals-table"
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
              border: '1px solid var(--l500)',
            }}
          >
            <thead>
              <tr style={{ background: 'var(--m50)', borderBottom: '1px solid var(--l500)' }}>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>{t('admin.dream.col.created')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>{t('admin.dream.col.category')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>{t('admin.dream.col.title')}</th>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>{t('admin.dream.col.status')}</th>
                <th style={{ textAlign: 'right', padding: '8px 10px' }}>{t('admin.dream.col.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p) => (
                <tr key={p.id} style={{ borderBottom: '1px solid var(--l500)' }}>
                  <td style={{ padding: '8px 10px', color: 'var(--m600)', whiteSpace: 'nowrap' }}>
                    {formatTs(p.created_at)}
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <code style={{ fontSize: 11 }}>{p.category}</code>
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <div style={{ fontWeight: 500 }}>{p.title}</div>
                    {p.suggestion && (
                      <div style={{ fontSize: 11, color: 'var(--m600)', marginTop: 2 }}>
                        {p.suggestion.slice(0, 120)}
                        {p.suggestion.length > 120 ? '…' : ''}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <span
                      style={{
                        color: STATUS_COLOR[p.status] || 'var(--m600)',
                        fontWeight: 500,
                      }}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                    <button
                      type="button"
                      className="cs-btn ok"
                      onClick={() => handleApply(p.id)}
                      disabled={applyingId === p.id || p.status === 'draft'}
                      data-testid={`dream-apply-${p.id}`}
                      title={
                        p.status === 'draft'
                          ? t('admin.dream.apply.requires_accepted')
                          : t('admin.dream.apply.cta')
                      }
                      style={{ opacity: applyingId === p.id || p.status === 'draft' ? 0.5 : 1 }}
                    >
                      {applyingId === p.id ? '…' : t('admin.dream.apply.cta')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Recently Applied ──────────────────────────────────────── */}
      {recentApplied.length > 0 && (
        <section data-testid="dream-applied-section" style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px 0' }}>
            {t('admin.dream.applied.title')}
          </h3>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {recentApplied.map((p) => (
              <li
                key={p.id}
                style={{
                  padding: '8px 10px',
                  borderLeft: '3px solid #137333',
                  background: 'var(--m50)',
                  marginBottom: 6,
                  fontSize: 13,
                }}
              >
                <div style={{ fontWeight: 500 }}>{p.title}</div>
                <div style={{ fontSize: 11, color: 'var(--m600)' }}>
                  <code>{p.category}</code> · {formatTs(p.created_at)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ── Recent Runs ───────────────────────────────────────────── */}
      <section data-testid="dream-runs-section">
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px 0' }}>
          {t('admin.dream.runs.title')}
        </h3>
        {runs.length === 0 ? (
          <div className="im-empty">{t('admin.dream.runs.empty')}</div>
        ) : (
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 12,
              border: '1px solid var(--l500)',
            }}
          >
            <thead>
              <tr style={{ background: 'var(--m50)', borderBottom: '1px solid var(--l500)' }}>
                <th style={{ textAlign: 'left', padding: '6px 10px' }}>{t('admin.dream.col.started')}</th>
                <th style={{ textAlign: 'left', padding: '6px 10px' }}>{t('admin.dream.col.status')}</th>
                <th style={{ textAlign: 'right', padding: '6px 10px' }}>{t('admin.dream.col.tokens')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--l500)' }}>
                  <td style={{ padding: '6px 10px', color: 'var(--m600)', whiteSpace: 'nowrap' }}>
                    {formatTs(r.started_at)}
                  </td>
                  <td style={{ padding: '6px 10px' }}>
                    <span style={{ color: STATUS_COLOR[r.status] || 'var(--m600)', fontWeight: 500 }}>
                      {r.status}
                    </span>
                    {r.error && (
                      <div style={{ fontSize: 10, color: '#c5221f' }}>{r.error.slice(0, 80)}</div>
                    )}
                  </td>
                  <td style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--m600)' }}>
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
