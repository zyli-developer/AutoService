import { useTranslation } from '@autoservice/i18n';

export interface MetricBreach {
  metric: string;
  baseline: number;
  current: number;
}

interface MetricCompareProps {
  breaches: MetricBreach[];
}

function formatValue(metric: string, v: number): string {
  // CSAT-like metrics come through as small floats; ms-style metrics as
  // large integers. The monitor payload is authoritative on the shape,
  // so we format cheaply rather than schema-guessing.
  if (metric.endsWith('_ms')) return `${Math.round(v)}ms`;
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function deltaClass(baseline: number, current: number): string {
  // A breach means the metric crossed its threshold — direction of
  // "bad" depends on the metric (higher ms = worse; lower csat = worse).
  // The caller already decided this is a breach, so we just flag visual
  // emphasis rather than re-judging severity.
  return current === baseline ? 'metric-compare-row' : 'metric-compare-row breach';
}

export function MetricCompare({ breaches }: MetricCompareProps) {
  const { t } = useTranslation();
  if (!breaches || breaches.length === 0) return null;

  return (
    <div className="cs-card" data-testid="metric-compare" style={{ marginTop: 12 }}>
      <div className="cs-ct" style={{ marginBottom: 8 }}>
        {t('admin.dream.canary.metric_compare.title')}
      </div>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 12,
        }}
      >
        <thead>
          <tr
            style={{
              background: 'var(--color-bg-surface-tinted)',
              borderBottom: '1px solid var(--color-border)',
            }}
          >
            <th style={{ textAlign: 'left', padding: '6px 10px', fontWeight: 500 }}>
              {t('admin.dream.canary.metric_compare.metric')}
            </th>
            <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: 500 }}>
              {t('admin.dream.canary.metric_compare.baseline')}
            </th>
            <th style={{ textAlign: 'right', padding: '6px 10px', fontWeight: 500 }}>
              {t('admin.dream.canary.metric_compare.current')}
            </th>
          </tr>
        </thead>
        <tbody>
          {breaches.map((b) => (
            <tr
              key={b.metric}
              className={deltaClass(b.baseline, b.current)}
              data-testid={`metric-compare-row-${b.metric}`}
              style={{
                borderBottom: '1px solid var(--color-border-subtle, var(--color-border))',
              }}
            >
              <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)' }}>
                {b.metric}
              </td>
              <td
                style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--color-text-secondary)' }}
                data-testid={`metric-compare-baseline-${b.metric}`}
              >
                {formatValue(b.metric, b.baseline)}
              </td>
              <td
                style={{
                  padding: '6px 10px',
                  textAlign: 'right',
                  fontWeight: 600,
                  color: 'var(--color-danger-text, var(--color-danger))',
                }}
                data-testid={`metric-compare-current-${b.metric}`}
              >
                {formatValue(b.metric, b.current)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
