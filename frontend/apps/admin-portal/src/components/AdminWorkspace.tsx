import { Button, Layout, Tabs, Tag, Typography } from 'antd';
import { LogoutOutlined } from '@ant-design/icons';
import { useAdminStore } from '../store/adminStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { WizardTab } from './WizardTab';
import { DashboardTab } from './DashboardTab';
import { NotificationsTab } from './NotificationsTab';
import { ProposalsTab } from './ProposalsTab';

const { Header, Content } = Layout;

const WS_URL =
  typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL
    ? (import.meta as any).env.VITE_WS_URL
    : 'ws://localhost:9999/ws/admin';

export function AdminWorkspace() {
  const tenantId = useAdminStore((s) => s.tenantId);
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);
  const logout = useAdminStore((s) => s.logout);
  const { status } = useWebSocket(WS_URL, 'admin-portal');

  return (
    <Layout style={{ minHeight: '100vh' }} data-testid="admin-workspace">
      <Header style={{ color: '#fff', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0, flex: 1 }}>
          AutoService 管理后台
        </Typography.Title>
        <Tag color={status === 'open' ? 'green' : 'default'}>WS: {status}</Tag>
        <Typography.Text style={{ color: '#ccc', marginRight: 8 }} data-testid="tenant-id">
          {tenantId}
        </Typography.Text>
        <Button
          icon={<LogoutOutlined />}
          size="small"
          type="text"
          style={{ color: '#ccc' }}
          data-testid="btn-logout"
          onClick={logout}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as AdminState['activeTab'])}
          data-testid="admin-tabs"
          items={[
            { key: 'wizard', label: '向导', children: <WizardTab /> },
            { key: 'dashboard', label: '仪表盘', children: <DashboardTab /> },
            { key: 'notifications', label: '通知', children: <NotificationsTab /> },
            { key: 'proposals', label: '提案', children: <ProposalsTab /> },
          ]}
        />
      </Content>
    </Layout>
  );
}

type AdminState = import('../store/adminStore').AdminState;
