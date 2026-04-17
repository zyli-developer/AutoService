import { useEffect, useState } from 'react';
import { fetchJSON, postJSON } from '../api';

interface CanaryData {
  stage: number;
  percentage: number;
  can_advance: boolean;
  history: unknown[];
  monitor: { status: string; breaches?: { metric: string; baseline: number; current: number }[] };
}

export function CanaryProgress() {
  const [data, setData] = useState<CanaryData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetchJSON<CanaryData>('/api/canary/status')
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading) return <div className="cs-card" data-testid="canary-progress"><div className="im-empty">加载灰度状态...</div></div>;
  if (!data) return <div className="cs-card" data-testid="canary-progress"><div className="im-empty" data-testid="canary-empty">暂无灰度数据</div></div>;

  const stages = [0, 5, 25, 100];
  const currentIdx = stages.findIndex(s => s >= data.percentage);

  return (
    <div className="cs-card" data-testid="canary-progress" style={{ marginTop: 14 }}>
      <div className="cs-ct">📈 灰度发布进度</div>

      {/* Stage progress bar */}
      <div className="bar" data-testid="canary-steps" style={{ marginBottom: 12 }}>
        {stages.map((s, i) => (
          <div key={s} style={{
            background: i <= currentIdx ? 'var(--m600)' : 'var(--oat)',
            flex: 1, height: 8, borderRadius: 4,
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--silver)', marginBottom: 12 }}>
        {stages.map(s => <span key={s}>{s}%</span>)}
      </div>

      <div className="cs-row" data-testid="canary-percentage">
        <span>当前</span>
        <span style={{ color: 'var(--m600)', fontWeight: 700 }} data-testid="canary-status-tag">
          {data.percentage}% · {data.monitor.status}
        </span>
      </div>

      {/* Monitor breaches */}
      {data.monitor.breaches && data.monitor.breaches.length > 0 && (
        <div style={{ marginTop: 12 }} data-testid="canary-metrics-table">
          {data.monitor.breaches.map((b) => (
            <div className="cs-row" key={b.metric}>
              <span>{b.metric}</span>
              <span style={{ color: 'var(--p)', fontWeight: 700 }} data-testid="metric-breached">
                {b.baseline.toFixed(2)} → {b.current.toFixed(2)}
              </span>
            </div>
          ))}
          <div className="cs-pg warn" data-testid="breach-count" style={{ marginTop: 8 }}>
            ⚠ {data.monitor.breaches.length} 项指标超阈值
          </div>
        </div>
      )}

      {/* Controls */}
      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
        <button className="cs-btn ok" onClick={() => postJSON('/api/canary/advance').then(load)}>Advance</button>
        <button className="cs-btn" onClick={() => postJSON('/api/canary/rollback').then(load)} style={{ background: 'var(--p)', color: '#fff', border: 'none' }}>Rollback</button>
      </div>
    </div>
  );
}
