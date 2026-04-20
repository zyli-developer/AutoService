import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { fetchJSON } from '../api';

interface Invoice {
  period: string;
  total: number;
  breakdown: { tier: string; count: number; rate: number; subtotal: number }[];
  metrics_snapshot?: Record<string, unknown>;
  status?: string;
}

export function BillingTab() {
  const { t } = useTranslation();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => {
    setLoading(true);
    fetchJSON<Invoice[]>('/api/billing/invoices')
      .then(setInvoices)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const inv = invoices[selectedIdx];

  return (
    <div data-testid="tab-billing">
      {loading && <div className="im-empty" data-testid="billing-loading">{t('common.loading')}</div>}
      {!loading && invoices.length === 0 && <div className="im-empty">{t('admin.billing.empty')}</div>}
      {!loading && inv && (
        <div className="cs-split" style={{ ['--split-left' as string]: '200px' }}>
          <div className="cs-split-list" data-testid="billing-controls">
            {invoices.map((item, i) => (
              <button
                key={i}
                type="button"
                className={`cs-list-row ${i === selectedIdx ? 'active' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                {item.period}
              </button>
            ))}
          </div>
          <div className="cs-split-detail">
            <div className="cs-card" data-testid="invoice-detail">
              <div className="cs-ct">{t('admin.billing.title', { month: inv.period })}</div>
              <div className="cs-row">
                <span>{t('admin.billing.total')}</span>
                <span
                  style={{ color: 'var(--m600)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}
                  data-testid="stat-total"
                >
                  ${inv.total.toFixed(2)}
                </span>
              </div>
              <div className="cs-row"><span>{t('admin.billing.status')}</span><span>{inv.status || 'generated'}</span></div>
            </div>

            {inv.breakdown && inv.breakdown.length > 0 && (
              <div className="cs-card" style={{ marginTop: 14 }} data-testid="breakdown-card">
                <div className="cs-ct">{t('admin.billing.tier_breakdown')}</div>
                {inv.breakdown.map((b, i) => (
                  <div className="cs-row" key={i}>
                    <span>{b.tier} × {b.count}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>${b.subtotal.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
