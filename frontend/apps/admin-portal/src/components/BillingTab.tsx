import { useEffect, useState } from 'react';

interface BillingBreakdown { tier: string; count: number; rate: number; subtotal: number; }
interface InvoiceUI {
  id: string; period: string; generated_at: string;
  conversation_count: number; total: number; breakdown: BillingBreakdown[]; currency: string;
}

const TIER_STYLES: Record<string, string> = {
  free: 'var(--m600)', starter: 'var(--s800)', pro: 'var(--u500)', enterprise: 'var(--l700)',
};

function mockLoadInvoices(): Promise<InvoiceUI[]> {
  return new Promise((resolve) => setTimeout(() => resolve([
    { id: 'inv_001', period: '2026-04', generated_at: new Date().toISOString(), conversation_count: 2500, total: 500, breakdown: [
      { tier: 'free', count: 100, rate: 0, subtotal: 0 }, { tier: 'starter', count: 900, rate: 0.5, subtotal: 450 }, { tier: 'pro', count: 1500, rate: 0.3, subtotal: 450 },
    ], currency: 'USD' },
    { id: 'inv_002', period: '2026-03', generated_at: new Date(Date.now() - 30 * 86400000).toISOString(), conversation_count: 800, total: 350, breakdown: [
      { tier: 'free', count: 100, rate: 0, subtotal: 0 }, { tier: 'starter', count: 700, rate: 0.5, subtotal: 350 },
    ], currency: 'USD' },
  ]), 500));
}

function exportCSV(inv: InvoiceUI) {
  const rows = [['Tier','Count','Rate','Subtotal'], ...inv.breakdown.map(b => [b.tier, b.count, b.rate, b.subtotal]), ['Total', inv.conversation_count, '', inv.total]];
  const blob = new Blob([rows.map(r => r.join(',')).join('\n')], { type: 'text/csv' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `invoice-${inv.period}.csv`; a.click();
}

export function BillingTab() {
  const [invoices, setInvoices] = useState<InvoiceUI[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => { setLoading(true); mockLoadInvoices().then(d => { setInvoices(d); setLoading(false); }); }, []);

  const inv = invoices[selectedIdx];

  return (
    <div data-testid="tab-billing">
      {loading && <div className="im-empty" data-testid="billing-loading">加载账单...</div>}
      {!loading && inv && (
        <>
          {/* Period selector */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 14 }} data-testid="billing-controls">
            {invoices.map((item, i) => (
              <button
                key={item.id}
                className={`cs-wiz-step ${i === selectedIdx ? 'cur' : ''}`}
                onClick={() => setSelectedIdx(i)}
                data-testid={i === 0 ? 'select-period' : undefined}
              >
                {item.period}
              </button>
            ))}
            <button className="cs-btn" data-testid="btn-export-csv" onClick={() => exportCSV(inv)} style={{ marginLeft: 'auto' }}>
              ⬇ 导出 CSV
            </button>
          </div>

          {/* Summary */}
          <div className="cs-card" data-testid="invoice-detail">
            <div className="cs-ct">💰 账单 · {inv.period}</div>
            <div className="cs-row"><span>总金额</span><span style={{ color: 'var(--m600)', fontWeight: 700, fontFamily: 'var(--font-mono)' }} data-testid="stat-total">${inv.total.toFixed(2)}</span></div>
            <div className="cs-row"><span>对话总数</span><span data-testid="stat-conversations">{inv.conversation_count}</span></div>
            <div className="cs-row"><span>账期</span><span data-testid="stat-period">{inv.period}</span></div>
            <div className="cs-row"><span>币种</span><span>{inv.currency}</span></div>
          </div>

          {/* Breakdown */}
          <div className="cs-card" style={{ marginTop: 14 }} data-testid="breakdown-card">
            <div className="cs-ct">📊 阶梯明细</div>
            <div data-testid="breakdown-table">
              {inv.breakdown.map((b, i) => (
                <div className="cs-row" key={i}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: TIER_STYLES[b.tier] || 'var(--silver)', display: 'inline-block' }} />
                    {b.tier} × {b.count}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>${b.subtotal.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* History */}
          <div className="cs-card" style={{ marginTop: 14 }} data-testid="invoice-history">
            <div className="cs-ct">📋 历史账单</div>
            {invoices.map((item) => (
              <div className="cs-row" key={item.id} data-testid="history-table">
                <span>{item.period} · {item.conversation_count} 对话</span>
                <span style={{ color: 'var(--m600)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>${item.total.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
