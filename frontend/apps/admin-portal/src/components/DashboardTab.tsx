import { useEffect, useState } from 'react';
import { fetchJSON } from '../api';
import { CanaryProgress } from './CanaryProgress';

interface SLAMetric {
  p50: number | null;
  p95: number | null;
  count: number;
  min: number | null;
  max: number | null;
}

const METRIC_LABELS: Record<string, string> = {
  first_reply_ms: 'onboard 首屏',
  accept_ms: '接单等待',
  csat_score: 'CSAT',
  resolution_rate: '结案率',
  digest_rate: '消化率',
  complaint_rate: '投诉率',
  ttfb_ms: '首字节时间',
};

function formatValue(key: string, m: SLAMetric): string {
  if (m.p50 === null) return '—';
  if (key.includes('rate')) return `${(m.p50 * 100).toFixed(1)}%`;
  if (key === 'csat_score') return m.p50.toFixed(1);
  if (key.includes('ms')) return `${m.p50.toFixed(0)}ms`;
  return m.p50.toFixed(2);
}

export function DashboardTab() {
  const [sla, setSla] = useState<Record<string, SLAMetric> | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchJSON<Record<string, SLAMetric>>('/api/sla/summary')
      .then(setSla)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div data-testid="tab-dashboard">
      {/* SLA Metrics — fetched from /api/sla/summary */}
      <div className="cs-card">
        <div className="cs-ct">◉ 实时 SLA（7 指标）</div>
        {error && <div className="cs-pg warn">{error}</div>}
        {!sla && !error && <div className="im-empty">加载中...</div>}
        {sla && Object.entries(sla).map(([key, m]) => (
          <div className="cs-row" key={key} data-testid={`metric-${key}`}>
            <span>{METRIC_LABELS[key] || key}</span>
            <span style={{
              color: m.count > 0 ? 'var(--m600)' : 'var(--silver)',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
            }}>
              {formatValue(key, m)}
              {m.p95 !== null && (
                <span style={{ color: 'var(--silver)', fontWeight: 400, marginLeft: 8, fontSize: 10 }}>
                  P95: {key.includes('ms') ? `${m.p95.toFixed(0)}ms` : m.p95.toFixed(2)}
                </span>
              )}
            </span>
          </div>
        ))}
      </div>

      {/* Agent Status */}
      <div className="cs-card" style={{ marginTop: 14 }}>
        <div className="cs-ct">🤖 Agent 状态</div>
        {['customer', 'translate', 'lead', 'triage'].map((a) => (
          <div className="cs-row" key={a} data-testid={`agent-card-${a}`}>
            <span>{a} Agent</span>
            <span style={{ color: 'var(--m600)', fontWeight: 700 }}>online</span>
          </div>
        ))}
      </div>

      {/* Canary Progress */}
      <CanaryProgress />
    </div>
  );
}
