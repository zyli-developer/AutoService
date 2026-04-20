import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { fetchJSON } from '../api';

interface TrendPoint {
  date: string;
  count: number;
}

/**
 * SVG line chart showing takeover counts over time.
 * Fetches data from /api/metrics/takeover-trend.
 */
export function TakeoverTrendChart() {
  const { t } = useTranslation();
  const [data, setData] = useState<TrendPoint[] | null>(null);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState<'week' | 'month'>('week');

  useEffect(() => {
    fetchJSON<TrendPoint[]>(`/api/metrics/takeover-trend?period=${period}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [period]);

  const hasData = data && data.some((p) => p.count > 0);

  // Chart dimensions
  const W = 480;
  const H = 180;
  const PAD_L = 36;
  const PAD_R = 12;
  const PAD_T = 16;
  const PAD_B = 32;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  function renderChart(points: TrendPoint[]) {
    const maxCount = Math.max(...points.map((p) => p.count), 1);
    const stepX = chartW / Math.max(points.length - 1, 1);

    const coords = points.map((p, i) => ({
      x: PAD_L + i * stepX,
      y: PAD_T + chartH - (p.count / maxCount) * chartH,
      ...p,
    }));

    const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ');
    const areaPath = `${linePath} L${coords[coords.length - 1].x},${PAD_T + chartH} L${coords[0].x},${PAD_T + chartH} Z`;

    // Y-axis labels (0 and max)
    const yLabels = [
      { val: maxCount, y: PAD_T },
      { val: Math.round(maxCount / 2), y: PAD_T + chartH / 2 },
      { val: 0, y: PAD_T + chartH },
    ];

    // X-axis labels — show a subset to avoid overlap
    const labelInterval = points.length <= 7 ? 1 : Math.ceil(points.length / 6);

    return (
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
        {/* Grid lines */}
        {yLabels.map((yl) => (
          <line
            key={yl.val}
            x1={PAD_L}
            y1={yl.y}
            x2={W - PAD_R}
            y2={yl.y}
            stroke="var(--silver, #ccc)"
            strokeDasharray="3,3"
            strokeWidth={0.5}
          />
        ))}

        {/* Area fill */}
        <path d={areaPath} fill="var(--m100, #e0edff)" opacity={0.5} />

        {/* Line */}
        <path d={linePath} fill="none" stroke="var(--m600, #2563eb)" strokeWidth={2} />

        {/* Dots */}
        {coords.map((c, i) => (
          <circle key={i} cx={c.x} cy={c.y} r={3} fill="var(--m600, #2563eb)">
            <title>{c.date}: {c.count}</title>
          </circle>
        ))}

        {/* Y-axis labels */}
        {yLabels.map((yl) => (
          <text
            key={`y-${yl.val}`}
            x={PAD_L - 6}
            y={yl.y + 4}
            textAnchor="end"
            fontSize={10}
            fill="var(--silver, #999)"
          >
            {yl.val}
          </text>
        ))}

        {/* X-axis labels */}
        {coords.map(
          (c, i) =>
            i % labelInterval === 0 && (
              <text
                key={`x-${i}`}
                x={c.x}
                y={H - 4}
                textAnchor="middle"
                fontSize={9}
                fill="var(--silver, #999)"
              >
                {c.date.slice(5)}
              </text>
            ),
        )}
      </svg>
    );
  }

  return (
    <div className="cs-card" style={{ marginTop: 14 }} data-testid="takeover-trend">
      <div className="cs-ct" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>{t('admin.dashboard.takeover_trend')}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {(['week', 'month'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                fontSize: 11,
                padding: '2px 8px',
                border: '1px solid var(--silver, #ccc)',
                borderRadius: 4,
                background: period === p ? 'var(--m600, #2563eb)' : 'transparent',
                color: period === p ? '#fff' : 'inherit',
                cursor: 'pointer',
              }}
            >
              {p === 'week' ? t('admin.dashboard.range.7day') : t('admin.dashboard.range.30day')}
            </button>
          ))}
        </span>
      </div>

      {error && <div className="cs-pg warn">{error}</div>}
      {!data && !error && <div className="im-empty">{t('common.loading')}</div>}
      {data && !hasData && (
        <div className="im-empty" style={{ padding: 24, textAlign: 'center', color: 'var(--silver, #999)' }}>
          {t('admin.dashboard.takeover_empty')}
        </div>
      )}
      {data && hasData && renderChart(data)}
    </div>
  );
}
