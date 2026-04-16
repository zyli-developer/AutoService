import { Card, Col, Row, Statistic, Tag, Typography } from 'antd';

interface AgentInfo {
  key: string;
  name: string;
  online: boolean;
}

const agents: AgentInfo[] = [
  { key: 'customer', name: 'Customer Agent', online: true },
  { key: 'translate', name: 'Translate Agent', online: true },
  { key: 'lead', name: 'Lead Agent', online: true },
  { key: 'triage', name: 'Triage Agent', online: true },
];

const metrics = [
  { testId: 'metric-takeover', title: '接管次数', value: 23 },
  { testId: 'metric-csat', title: 'CSAT', value: 4.6, suffix: '/ 5.0' },
  { testId: 'metric-resolution', title: '升级→结案率', value: 87, suffix: '%' },
];

export function DashboardTab() {
  return (
    <div data-testid="tab-dashboard">
      <Typography.Title level={4}>运营仪表盘</Typography.Title>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {agents.map((agent) => (
          <Col key={agent.key} xs={24} sm={12} md={6}>
            <Card data-testid={`agent-card-${agent.key}`} size="small">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>{agent.name}</span>
                <Tag color={agent.online ? 'green' : 'default'}>
                  {agent.online ? 'online' : 'offline'}
                </Tag>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]}>
        {metrics.map((m) => (
          <Col key={m.testId} xs={24} sm={8}>
            <Card data-testid={m.testId}>
              <Statistic title={m.title} value={m.value} suffix={m.suffix} />
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
