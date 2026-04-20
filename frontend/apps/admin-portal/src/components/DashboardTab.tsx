import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
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

const METRIC_LABEL_KEYS: Record<string, string> = {
  first_reply_ms: 'admin.dashboard.onboard_first_screen',
  accept_ms: 'admin.dashboard.accept_wait',
  csat_score: 'admin.dashboard.csat',
  resolution_rate: 'admin.dashboard.resolution_rate',
  digest_rate: 'admin.dashboard.digest_rate',
  complaint_rate: 'admin.dashboard.complaint_rate',
  ttfb_ms: 'admin.dashboard.ttfb',
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
  const { t } = useTranslation();
  return (
    <div className="cs-row" key={metricKey} data-testid={`metric-${metricKey}`}>
      <span>{METRIC_LABEL_KEYS[metricKey] ? t(METRIC_LABEL_KEYS[metricKey]) : metricKey}</span>
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
  { value: '5m', labelKey: 'admin.dashboard.range.5min' },
  { value: '1h', labelKey: 'admin.dashboard.range.1hour' },
  { value: '24h', labelKey: 'admin.dashboard.range.24hour' },
] as const;

export function DashboardTab() {
  const { t } = useTranslation();
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
      {/* Time Slice Selector */}
      <div className="cs-wiz" style={{ marginBottom: 14 }}>
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`cs-wiz-step ${period === opt.value ? 'cur' : ''}`}
            data-testid={`period-${opt.value}`}
            onClick={() => setPeriod(opt.value)}
          >
            {t(opt.labelKey)}
          </button>
        ))}
      </div>

      {/* Primary KPIs — big grid */}
      {error && <div className="cs-pg warn" style={{ marginTop: 14 }}>{error}</div>}
      {!sla && !error && <div className="im-empty" style={{ marginTop: 14 }}>{t('common.loading')}</div>}

      {sla && (
        <>
          <div className="cs-kpi-grid">
            {primaryEntries.map(([key, m]) => (
              <div className="cs-kpi" key={key} data-testid={`metric-${key}`}>
                <div className="cs-kpi-label">{METRIC_LABEL_KEYS[key] ? t(METRIC_LABEL_KEYS[key]) : key}</div>
                <div className={`cs-kpi-value ${m.count > 0 ? '' : 'muted'}`}>
                  {formatValue(key, m)}
                </div>
                <div className="cs-kpi-sparkline" />
              </div>
            ))}
          </div>

          {/* Aux 2-column */}
          <div className="cs-aux-grid">
            <div className="cs-card">
              <div className="cs-ct">{t('admin.dashboard.agent_status')}</div>
              {['customer', 'translate', 'lead', 'triage'].map((a) => (
                <div className="cs-row" key={a} data-testid={`agent-card-${a}`}>
                  <span>{a} Agent</span>
                  <span style={{ color: 'var(--m600)', fontWeight: 700 }}>online</span>
                </div>
              ))}
            </div>
            <div className="cs-card">
              <div className="cs-ct">{t('admin.dashboard.aux_metrics')}</div>
              {auxiliaryEntries.map(([key, m]) => (
                <MetricRow key={key} metricKey={key} m={m} />
              ))}
            </div>
          </div>
        </>
      )}

      {/* Full-width sections */}
      <CanaryProgress />
      <TakeoverTrendChart />
      <LeaderboardTable />
    </div>
  );
}
