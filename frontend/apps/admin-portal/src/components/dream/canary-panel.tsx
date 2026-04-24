import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { fetchJSON, postJSON } from '../../api';
import { MetricCompare, type MetricBreach } from './metric-compare';

export interface CanaryPanelProposal {
  id: string;
  title: string;
  category: string;
  status: string;
  suggestion?: string;
}

interface CanaryPanelProps {
  proposal: CanaryPanelProposal;
  onReload: () => void;
}

interface CanaryStatus {
  stage: number;
  percentage: number;
  can_advance: boolean;
  history: unknown[];
  monitor: {
    status: string;
    breaches?: MetricBreach[];
  };
}

const STAGES = [0, 5, 25, 100];

type BusyAction = 'approve' | 'reject' | 'apply' | 'advance' | 'rollback';

export function CanaryPanel({ proposal, onReload }: CanaryPanelProps) {
  const { t } = useTranslation();
  const [canary, setCanary] = useState<CanaryStatus | null>(null);
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadCanary = useCallback(() => {
    fetchJSON<CanaryStatus>('/api/canary/status')
      .then(setCanary)
      .catch(() => setCanary(null));
  }, []);

  useEffect(() => {
    loadCanary();
  }, [loadCanary]);

  const canApply = proposal.status === 'accepted';
  // Approve is idempotent-aware: only meaningful on a draft.
  const canApprove = proposal.status === 'draft';
  // Reject can revert an accepted proposal as well as discard a draft,
  // but never a terminal state (applied / rejected).
  const canReject = proposal.status === 'draft' || proposal.status === 'accepted';
  const canAdvance = !!canary && canary.can_advance && canary.percentage < 100;
  const canRollback = !!canary && canary.percentage > 0;

  // The slash-command dispatcher lives at ``/api/management/chat-legacy``
  // with query-string args (api_routes.py:1291-1371). The M2
  // ``/api/management/chat`` handler is the ``_master`` LLM pass-through
  // and does NOT dispatch /approve | /reject. This helper keeps the two
  // call sites from drifting onto the wrong endpoint.
  const sendSlashCommand = (command: string) =>
    postJSON<unknown>(
      `/api/management/chat-legacy?message=${encodeURIComponent(command)}`,
    );

  const handleApprove = async () => {
    if (!canApprove || busy) return;
    setBusy('approve');
    setErrorMsg(null);
    try {
      // CON-04 respected: /approve routes through ProposalPipeline
      // .update_status → status=accepted. Apply remains the sole writer
      // of status=applied.
      await sendSlashCommand(`/approve ${proposal.id}`);
      loadCanary();
      onReload();
    } catch (e) {
      setErrorMsg(
        t('admin.dream.canary.error.approve_failed', { id: proposal.id }),
      );
    } finally {
      setBusy(null);
    }
  };

  const handleReject = async () => {
    if (!canReject || busy) return;
    setBusy('reject');
    setErrorMsg(null);
    try {
      await sendSlashCommand(`/reject ${proposal.id}`);
      loadCanary();
      onReload();
    } catch (e) {
      setErrorMsg(
        t('admin.dream.canary.error.reject_failed', { id: proposal.id }),
      );
    } finally {
      setBusy(null);
    }
  };

  const handleAdvance = async () => {
    if (!canAdvance || busy) return;
    const next = STAGES.find((s) => s > (canary?.percentage ?? 0)) ?? 100;
    if (!window.confirm(
      t('admin.dream.canary.advance.confirm', { next: String(next) }),
    )) {
      return;
    }
    setBusy('advance');
    setErrorMsg(null);
    try {
      await postJSON<unknown>('/api/canary/advance', undefined);
      loadCanary();
    } catch (e) {
      setErrorMsg(t('admin.dream.canary.error.advance_failed'));
    } finally {
      setBusy(null);
    }
  };

  const handleRollback = async () => {
    if (!canRollback || busy) return;
    if (!window.confirm(t('admin.dream.canary.rollback.confirm'))) return;
    setBusy('rollback');
    setErrorMsg(null);
    try {
      await postJSON<unknown>('/api/canary/rollback', undefined);
      loadCanary();
    } catch (e) {
      setErrorMsg(t('admin.dream.canary.error.rollback_failed'));
    } finally {
      setBusy(null);
    }
  };

  const handleApply = async () => {
    if (!canApply || busy) return;
    setBusy('apply');
    setErrorMsg(null);
    try {
      // CON-04 red line: this is the ONLY endpoint that transitions
      // status → 'applied'. No client-side status mutation and no other
      // mutation endpoint is called from the Apply handler.
      await postJSON<unknown>(
        `/api/admin/proposals/${proposal.id}/apply`,
        undefined,
      );
      loadCanary();
      onReload();
    } catch (e) {
      setErrorMsg(
        t('admin.dream.canary.error.apply_failed', { id: proposal.id }),
      );
    } finally {
      setBusy(null);
    }
  };

  const percentage = canary?.percentage ?? 0;
  const currentIdx = STAGES.findIndex((s) => s >= percentage);
  const monitorStatus = canary?.monitor?.status ?? '—';
  const breaches: MetricBreach[] = canary?.monitor?.breaches ?? [];

  return (
    <section
      className="cs-card"
      data-testid="canary-panel"
      style={{ marginBottom: 16 }}
    >
      <div className="cs-ct" data-testid="canary-panel-title" style={{ marginBottom: 8 }}>
        {proposal.title}
      </div>
      <div
        style={{
          fontSize: 11,
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-mono)',
          marginBottom: 12,
        }}
      >
        {proposal.id} · {proposal.category} · {proposal.status}
      </div>

      {/* ── Canary progress bar ───────────────────────────────────── */}
      <div data-testid="canary-progress" style={{ marginBottom: 12 }}>
        <div
          className="bar"
          data-testid="canary-steps"
          style={{ display: 'flex', gap: 4, marginBottom: 6 }}
        >
          {STAGES.map((s, i) => (
            <div
              key={s}
              style={{
                flex: 1,
                height: 8,
                borderRadius: 4,
                background:
                  i <= currentIdx ? 'var(--m600)' : 'var(--oat, var(--color-border))',
              }}
            />
          ))}
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 10,
            color: 'var(--color-text-muted)',
            marginBottom: 8,
          }}
        >
          {STAGES.map((s) => (
            <span key={s}>{s}%</span>
          ))}
        </div>
        <div
          style={{
            fontSize: 12,
            display: 'flex',
            justifyContent: 'space-between',
          }}
          data-testid="canary-panel-status-row"
        >
          <span>{t('admin.dream.canary.stage_label')}</span>
          <span style={{ fontWeight: 600, color: 'var(--m600)' }}>
            {percentage}% · {monitorStatus}
          </span>
        </div>
        {/* Canary stage controls — Advance / Rollback (plan §Scope §2) */}
        <div
          style={{ marginTop: 10, display: 'flex', gap: 8, justifyContent: 'flex-end' }}
          data-testid="canary-panel-stage-controls"
        >
          <button
            type="button"
            className="cs-btn"
            data-testid="canary-panel-rollback-btn"
            onClick={handleRollback}
            disabled={!canRollback || busy !== null}
            title={t('admin.dream.canary.rollback.cta')}
            style={{ opacity: canRollback && busy === null ? 1 : 0.5 }}
          >
            {busy === 'rollback' ? '…' : t('admin.dream.canary.rollback.cta')}
          </button>
          <button
            type="button"
            className="cs-btn ok"
            data-testid="canary-panel-advance-btn"
            onClick={handleAdvance}
            disabled={!canAdvance || busy !== null}
            title={t('admin.dream.canary.advance.cta')}
            style={{ opacity: canAdvance && busy === null ? 1 : 0.5 }}
          >
            {busy === 'advance' ? '…' : t('admin.dream.canary.advance.cta')}
          </button>
        </div>
      </div>

      {/* ── Metric compare (breaches only render when present) ─────── */}
      <MetricCompare breaches={breaches} />

      {errorMsg && (
        <div
          role="alert"
          data-testid="canary-panel-error"
          style={{
            marginTop: 8,
            fontSize: 12,
            color: 'var(--color-danger-text, var(--color-danger))',
          }}
        >
          ⚠ {errorMsg}
        </div>
      )}

      {/* ── 3-button row: [Reject] [Approve] [🔒 Apply] ───────────── */}
      <div
        style={{ marginTop: 14, display: 'flex', gap: 8, justifyContent: 'flex-end' }}
      >
        <button
          type="button"
          className="cs-btn"
          data-testid="canary-panel-reject-btn"
          onClick={handleReject}
          disabled={!canReject || busy !== null}
          title={
            canReject
              ? t('admin.dream.canary.reject.cta')
              : t('admin.dream.canary.reject.unavailable')
          }
          style={{
            background: canReject ? 'var(--p)' : undefined,
            color: canReject ? '#fff' : undefined,
            border: canReject ? 'none' : undefined,
            opacity: canReject && busy === null ? 1 : 0.5,
          }}
        >
          {busy === 'reject' ? '…' : t('admin.dream.canary.reject.cta')}
        </button>
        <button
          type="button"
          className="cs-btn"
          data-testid="canary-panel-approve-btn"
          onClick={handleApprove}
          disabled={!canApprove || busy !== null}
          title={
            canApprove
              ? t('admin.dream.canary.approve.cta')
              : t('admin.dream.canary.approve.unavailable')
          }
          style={{ opacity: canApprove && busy === null ? 1 : 0.5 }}
        >
          {busy === 'approve' ? '…' : t('admin.dream.canary.approve.cta')}
        </button>
        <button
          type="button"
          className="cs-btn ok"
          data-testid="canary-panel-apply-btn"
          onClick={handleApply}
          disabled={!canApply || busy !== null}
          title={
            canApply
              ? t('admin.dream.apply.cta')
              : t('admin.dream.apply.requires_accepted')
          }
          style={{ opacity: canApply && busy === null ? 1 : 0.5 }}
        >
          🔒 {busy === 'apply' ? '…' : t('admin.dream.apply.cta')}
        </button>
      </div>
    </section>
  );
}
