import { useEffect, useState } from 'react';
import { fetchJSON } from '../api';
import { CanaryProgress } from './CanaryProgress';
import { TakeoverTrendChart } from './TakeoverTrendChart';
import { LeaderboardTable } from './LeaderboardTable';

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

/** Primary billing KPI keys (3 starred metrics) */
const PRIMARY_METRICS = ['csat_score', 'resolution_rate', 'digest_rate'];

/** Auxiliary KPI keys (secondary metrics) */
const AUXILIARY_METRICS = ['first_reply_ms', 'accept_ms', 'complaint_rate', 'ttfb_ms'];

function formatValue(key: string, m: SLAMetric): string {
  if (m.p50 === null) return '—';
  if (key.includes('rate')) return `${(m.p50 * 100).toFixed(1)}%`;
  if (key === 'csat_score') return m.p50.toFixed(1);
  if (key.includes('ms')) return `${m.p50.toFixed(0)}ms`;
  return m.p50.toFixed(2);
}

function MetricRow({ metricKey, m }: { metricKey: string; m: SLAMetric }) {
  return (
    <div className="cs-row" key={metricKey} data-testid={`metric-${metricKey}`}>
      <span>{METRIC_LABELS[metricKey] || metricKey}</span>
      <span style={{
        color: m.count > 0 ? 'var(--m600)' : 'var(--silver)',
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
      }}>
        {formatValue(metricKey, m)}
        {m.p95 !== null && (
          <span style={{ color: 'var(--silver)', fontWeight: 400, marginLeft: 8, fontSize: 10 }}>
            P95: {metricKey.includes('ms') ? `${m.p95.toFixed(0)}ms` : m.p95.toFixed(2)}
          </span>
        )}
      </span>
    </div>
  );
}

const PERIOD_OPTIONS = [
  { value: '5m', label: '近5分钟' },
  { value: '1h', label: '近1小时' },
  { value: '24h', label: '近24小时' },
] as const;

export function DashboardTab() {
  const [sla, setSla] = useState<Record<string, SLAMetric> | null>(null);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState<string>('5m');

  useEffect(() => {
    const url = period === '5m' ? '/api/sla/summary' : `/api/sla/summary?period=${period}`;
    fetchJSON<Record<string, SLAMetric>>(url)
      .then(setSla)
      .catch((e) => setError(e.message));
  }, [period]);

  const primaryEntries = sla
    ? PRIMARY_METRICS.filter((k) => k in sla).map((k) => [k, sla[k]] as const)
    : [];
  const auxiliaryEntries = sla
    ? AUXILIARY_METRICS.filter((k) => k in sla).map((k) => [k, sla[k]] as const)
    : [];

  return (
    <div data-testid="tab-dashboard">
      {/* --- Time Slice Selector (T6D.5) --- */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            data-testid={`period-${opt.value}`}
            onClick={() => setPeriod(opt.value)}
            style={{
              fontSize: 11,
              padding: '2px 8px',
              border: '1px solid var(--silver, #ccc)',
              borderRadius: 4,
              background: period === opt.value ? 'var(--m600, #2563eb)' : 'transparent',
              color: period === opt.value ? '#fff' : 'inherit',
              cursor: 'pointer',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* --- Top Section: Agent Status --- */}
      <div className="cs-card">
        <div className="cs-ct">🤖 Agent 状态</div>
        {['customer', 'translate', 'lead', 'triage'].map((a) => (
          <div className="cs-row" key={a} data-testid={`agent-card-${a}`}>
            <span>{a} Agent</span>
            <span style={{ color: 'var(--m600)', fontWeight: 700 }}>online</span>
          </div>
        ))}
      </div>

      {/* --- Middle Section: KPI Metrics --- */}
      {error && <div className="cs-pg warn" style={{ marginTop: 14 }}>{error}</div>}
      {!sla && !error && <div className="im-empty" style={{ marginTop: 14 }}>加载中...</div>}

      {sla && (
        <>
          {/* Primary billing KPIs (starred) */}
          <div className="cs-card" style={{ marginTop: 14 }}>
            <div className="cs-ct">⭐ 核心计费指标</div>
            {primaryEntries.map(([key, m]) => (
              <MetricRow key={key} metricKey={key} m={m} />
            ))}
          </div>

          {/* Auxiliary KPIs */}
          <div className="cs-card" style={{ marginTop: 14 }}>
            <div className="cs-ct">◉ 辅助运营指标</div>
            {auxiliaryEntries.map(([key, m]) => (
              <MetricRow key={key} metricKey={key} m={m} />
            ))}
          </div>
        </>
      )}

      {/* Canary Progress */}
      <CanaryProgress />

      {/* --- Bottom Section: Trend Charts & Leaderboard (T6D.3 + T6D.4) --- */}
      <TakeoverTrendChart />
      <LeaderboardTable />
    </div>
  );
}
