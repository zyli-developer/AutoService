import { useAdminStore } from '../store/adminStore';
import type { CanaryStage } from '../store/adminStore';

const STAGE_LABELS: Record<CanaryStage, string> = {
  disabled: '未启动', stage_5: '5%', stage_25: '25%', stage_100: '100%',
};
const STAGE_ORDER: CanaryStage[] = ['disabled', 'stage_5', 'stage_25', 'stage_100'];

const METRIC_LABELS: Record<string, string> = {
  csat: 'CSAT 评分', resolution_rate: '结案率', digest_rate: '摘要率',
  accept_wait_ms: '响应时间(ms)', complaint_rate: '投诉率',
};

export function CanaryProgress() {
  const canaryState = useAdminStore((s) => s.canaryState);

  if (!canaryState) {
    return (
      <div className="cs-card" data-testid="canary-progress">
        <div className="cs-ct">📈 灰度发布</div>
        <div className="im-empty" data-testid="canary-empty">暂无灰度发布</div>
      </div>
    );
  }

  const currentIdx = STAGE_ORDER.indexOf(canaryState.stage);

  return (
    <div className="cs-card" data-testid="canary-progress" style={{ marginTop: 14 }}>
      <div className="cs-ct">📈 灰度发布进度</div>

      {/* Stage progress bar */}
      <div className="bar" data-testid="canary-steps" style={{ marginBottom: 12 }}>
        {STAGE_ORDER.map((stage, i) => (
          <div key={stage} style={{
            background: i <= currentIdx ? (canaryState.rolledBack ? 'var(--p)' : 'var(--m600)') : 'var(--oat)',
            flex: 1,
            height: 8,
            borderRadius: 4,
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--silver)', marginBottom: 12 }}>
        {STAGE_ORDER.map((s) => <span key={s}>{STAGE_LABELS[s]}</span>)}
      </div>

      {/* Status */}
      <div className="cs-row" data-testid="canary-percentage">
        <span>当前阶段</span>
        <span style={{
          color: canaryState.rolledBack ? 'var(--p)' : 'var(--m600)',
          fontWeight: 700,
        }} data-testid="canary-status-tag">
          {canaryState.rolledBack ? '已回滚' : `灰度中 (${canaryState.percentage}%)`}
        </span>
      </div>

      {/* Metrics */}
      <div style={{ marginTop: 12 }} data-testid="canary-metrics-table">
        {canaryState.metrics.map((m) => (
          <div className="cs-row" key={m.name}>
            <span>{METRIC_LABELS[m.name] || m.name}</span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: 'var(--silver)', fontSize: 11 }}>{m.baseline.toFixed(2)}</span>
              <span>→</span>
              <span style={{
                color: m.breached ? 'var(--p)' : 'var(--m600)',
                fontWeight: 700,
              }} data-testid={m.breached ? 'metric-breached' : 'metric-ok'}>
                {m.current.toFixed(2)}
              </span>
            </span>
          </div>
        ))}
      </div>

      {canaryState.metrics.some(m => m.breached) && (
        <div className="cs-pg warn" data-testid="breach-count" style={{ marginTop: 8 }}>
          ⚠ {canaryState.metrics.filter(m => m.breached).length} 项指标超阈值
        </div>
      )}
    </div>
  );
}
