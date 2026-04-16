import { Card, Layout, Tag, Typography } from 'antd';
import { useTranslation } from '@autoservice/i18n';
import { useWebSocket } from './hooks/useWebSocket';

const { Header, Content } = Layout;

export function App() {
  const { t } = useTranslation();
  const { status, lastFrame } = useWebSocket('ws://localhost:9999/ws/operator', 'operator-console');

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ color: '#fff', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          {t('app.title')} · operator-console
        </Typography.Title>
        <Tag color={status === 'open' ? 'green' : 'default'}>WS: {status}</Tag>
      </Header>
      <Content style={{ padding: 24 }}>
        <Card title={t('app.placeholder')}>
          <Typography.Paragraph type="secondary">T2B.1-7 TODO</Typography.Paragraph>
          <pre style={{ maxHeight: 240, overflow: 'auto', background: '#fafafa', padding: 12 }}>
            {lastFrame ? JSON.stringify(lastFrame, null, 2) : '(no frames yet)'}
          </pre>
        </Card>
      </Content>
    </Layout>
  );
}
