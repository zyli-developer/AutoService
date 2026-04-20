import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { fetchJSON } from '../api';

interface OperatorRow {
  operator_id: string;
  name: string;
  handled: number;
  avg_csat: number;
  avg_response_ms: number;
}

function formatResponseTime(ms: number): string {
  if (ms === 0) return '—';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms.toFixed(0)}ms`;
}

export function LeaderboardTable() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<OperatorRow[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchJSON<OperatorRow[]>('/api/metrics/operator-leaderboard')
      .then((data) => {
        setRows(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  return (
    <div className="cs-card" style={{ marginTop: 14 }} data-testid="leaderboard-table">
      <div className="cs-ct">{t('admin.dashboard.leaderboard')}</div>
      {error && <div className="cs-pg warn">{error}</div>}
      {loading && !error && <div className="im-empty">{t('common.loading')}</div>}
      {!loading && !error && rows.length === 0 && (
        <div className="im-empty" data-testid="leaderboard-empty">{t('admin.dashboard.leaderboard.empty')}</div>
      )}
      {!loading && !error && rows.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--silver, #ccc)', textAlign: 'left' }}>
              <th style={{ padding: '6px 8px', fontWeight: 600 }}>{t('admin.dashboard.leaderboard.rank')}</th>
              <th style={{ padding: '6px 8px', fontWeight: 600 }}>{t('admin.dashboard.leaderboard.operator')}</th>
              <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>{t('admin.dashboard.leaderboard.volume')}</th>
              <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>{t('admin.dashboard.leaderboard.avg_csat')}</th>
              <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>{t('admin.dashboard.leaderboard.avg_response')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={row.operator_id}
                style={{ borderBottom: '1px solid var(--silver, #eee)' }}
                data-testid={`leaderboard-row-${idx}`}
              >
                <td style={{ padding: '6px 8px', fontWeight: 700, color: idx < 3 ? 'var(--m600, #1a73e8)' : undefined }}>
                  {idx + 1}
                </td>
                <td style={{ padding: '6px 8px' }}>{row.name || row.operator_id}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                  {row.handled}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                  {row.avg_csat > 0 ? row.avg_csat.toFixed(1) : '—'}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                  {formatResponseTime(row.avg_response_ms)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
