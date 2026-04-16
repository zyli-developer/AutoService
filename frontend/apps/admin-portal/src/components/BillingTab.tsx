import { useEffect, useState } from 'react';
import { Button, Card, Col, Row, Select, Space, Spin, Statistic, Table, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

interface BillingBreakdown {
  tier: string;
  count: number;
  rate: number;
  subtotal: number;
}

interface InvoiceUI {
  id: string;
  period: string;
  generated_at: string;
  conversation_count: number;
  total: number;
  breakdown: BillingBreakdown[];
  currency: string;
}

const TIER_COLORS: Record<string, string> = {
  free: 'green',
  starter: 'blue',
  pro: 'purple',
  enterprise: 'gold',
};

function mockLoadInvoices(): Promise<InvoiceUI[]> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const invoices: InvoiceUI[] = [
        {
          id: 'inv_001',
          period: '2026-04',
          generated_at: new Date().toISOString(),
          conversation_count: 2500,
          total: 500.00,
          breakdown: [
            { tier: 'free', count: 100, rate: 0, subtotal: 0 },
            { tier: 'starter', count: 900, rate: 0.5, subtotal: 450.00 },
            { tier: 'pro', count: 1500, rate: 0.3, subtotal: 450.00 },
          ],
          currency: 'USD',
        },
        {
          id: 'inv_002',
          period: '2026-03',
          generated_at: new Date(Date.now() - 30 * 86400000).toISOString(),
          conversation_count: 800,
          total: 350.00,
          breakdown: [
            { tier: 'free', count: 100, rate: 0, subtotal: 0 },
            { tier: 'starter', count: 700, rate: 0.5, subtotal: 350.00 },
          ],
          currency: 'USD',
        },
        {
          id: 'inv_003',
          period: '2026-02',
          generated_at: new Date(Date.now() - 60 * 86400000).toISOString(),
          conversation_count: 150,
          total: 25.00,
          breakdown: [
            { tier: 'free', count: 100, rate: 0, subtotal: 0 },
            { tier: 'starter', count: 50, rate: 0.5, subtotal: 25.00 },
          ],
          currency: 'USD',
        },
      ];
      resolve(invoices);
    }, 800);
  });
}

function exportCSV(invoice: InvoiceUI) {
  const rows = [
    ['Tier', 'Count', 'Rate', 'Subtotal'],
    ...invoice.breakdown.map((b) => [b.tier, b.count, b.rate, b.subtotal]),
    ['Total', invoice.conversation_count, '', invoice.total],
  ];
  const csv = rows.map((r) => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `invoice-${invoice.period}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const breakdownColumns = [
  { title: '阶梯', dataIndex: 'tier', key: 'tier', render: (t: string) => <Tag color={TIER_COLORS[t] || 'default'}>{t}</Tag> },
  { title: '对话数', dataIndex: 'count', key: 'count' },
  { title: '单价', dataIndex: 'rate', key: 'rate', render: (v: number) => `$${v.toFixed(2)}` },
  { title: '小计', dataIndex: 'subtotal', key: 'subtotal', render: (v: number) => `$${v.toFixed(2)}` },
];

export function BillingTab() {
  const [invoices, setInvoices] = useState<InvoiceUI[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    mockLoadInvoices().then((data) => {
      setInvoices(data);
      setLoading(false);
    });
  }, []);

  const selectedInvoice = selectedPeriod
    ? invoices.find((inv) => inv.period === selectedPeriod)
    : invoices[0];

  return (
    <div data-testid="tab-billing">
      <Typography.Title level={4}>账单管理</Typography.Title>

      {loading && (
        <div data-testid="billing-loading">
          <Spin tip="加载账单..." />
        </div>
      )}

      {!loading && invoices.length > 0 && (
        <>
          <Space style={{ marginBottom: 16 }} data-testid="billing-controls">
            <Select
              data-testid="select-period"
              style={{ width: 200 }}
              placeholder="选择账期"
              value={selectedPeriod || invoices[0]?.period}
              onChange={(v) => setSelectedPeriod(v)}
              options={invoices.map((inv) => ({ label: inv.period, value: inv.period }))}
            />
            {selectedInvoice && (
              <Button
                icon={<DownloadOutlined />}
                data-testid="btn-export-csv"
                onClick={() => exportCSV(selectedInvoice)}
              >
                导出 CSV
              </Button>
            )}
          </Space>

          {selectedInvoice && (
            <div data-testid="invoice-detail">
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="总金额"
                      value={selectedInvoice.total}
                      prefix="$"
                      precision={2}
                      data-testid="stat-total"
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="对话总数"
                      value={selectedInvoice.conversation_count}
                      data-testid="stat-conversations"
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="账期"
                      value={selectedInvoice.period}
                      data-testid="stat-period"
                    />
                  </Card>
                </Col>
              </Row>

              <Card title="阶梯明细" size="small" data-testid="breakdown-card">
                <Table
                  dataSource={selectedInvoice.breakdown.map((b, i) => ({ ...b, key: i }))}
                  columns={breakdownColumns}
                  pagination={false}
                  size="small"
                  data-testid="breakdown-table"
                />
              </Card>
            </div>
          )}

          <Card title="历史账单" size="small" style={{ marginTop: 16 }} data-testid="invoice-history">
            <Table
              dataSource={invoices.map((inv) => ({ ...inv, key: inv.id }))}
              columns={[
                { title: '账期', dataIndex: 'period', key: 'period' },
                { title: '对话数', dataIndex: 'conversation_count', key: 'count' },
                { title: '金额', dataIndex: 'total', key: 'total', render: (v: number) => `$${v.toFixed(2)}` },
                { title: '币种', dataIndex: 'currency', key: 'currency' },
              ]}
              pagination={false}
              size="small"
              data-testid="history-table"
            />
          </Card>
        </>
      )}
    </div>
  );
}
