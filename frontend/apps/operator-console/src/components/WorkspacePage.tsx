import { useState } from 'react';
import { Button, Input, Layout, Menu, Space, Tabs, Tag, Typography } from 'antd';
import { LogoutOutlined, PlusOutlined } from '@ant-design/icons';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { SquadPane } from './SquadPane';
import { ConnectionBanner } from './ConnectionBanner';

const { Sider, Content } = Layout;

const WS_URL =
  typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL
    ? (import.meta as any).env.VITE_WS_URL
    : 'ws://localhost:9999/ws/operator';

export function WorkspacePage() {
  const squads = useOperatorStore((s) => s.squads);
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const addSquad = useOperatorStore((s) => s.addSquad);
  const setActiveSquad = useOperatorStore((s) => s.setActiveSquad);

  const [newSquadId, setNewSquadId] = useState('');

  useOperatorWS(WS_URL);

  const handleAddSquad = () => {
    if (!newSquadId.trim()) return;
    addSquad(newSquadId.trim());
    setNewSquadId('');
  };

  return (
    <Layout style={{ minHeight: '100vh' }} data-testid="workspace-page">
      <Sider width={220} theme="dark">
        <div style={{ padding: '16px', color: '#fff', fontWeight: 'bold' }}>
          AutoService 工作台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={activeSquadId ? [activeSquadId] : []}
          items={squads.map((sq) => ({ key: sq, label: sq }))}
          onSelect={({ key }) => setActiveSquad(key)}
        />
        <div style={{ padding: 16 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              data-testid="input-squad-id"
              size="small"
              placeholder="Squad ID"
              value={newSquadId}
              onChange={(e) => setNewSquadId(e.target.value)}
              onPressEnter={handleAddSquad}
            />
            <Button
              size="small"
              icon={<PlusOutlined />}
              data-testid="btn-add-squad"
              onClick={handleAddSquad}
            />
          </Space.Compact>
        </div>
        <div style={{ padding: 16, marginTop: 'auto' }}>
          <Button
            icon={<LogoutOutlined />}
            size="small"
            type="text"
            style={{ color: '#ccc' }}
            data-testid="btn-logout"
            onClick={logout}
          >
            退出
          </Button>
        </div>
      </Sider>
      <Layout>
        <ConnectionBanner />
        <Content style={{ padding: 24 }}>
          <div style={{ marginBottom: 8 }}>
            <Tag color={wsStatus === 'open' ? 'green' : 'default'}>WS: {wsStatus}</Tag>
          </div>
          {squads.length === 0 ? (
            <Typography.Text type="secondary">请在左侧添加 Squad ID</Typography.Text>
          ) : (
            <Tabs
              activeKey={activeSquadId ?? squads[0]}
              onChange={setActiveSquad}
              items={squads.map((sq) => ({
                key: sq,
                label: sq,
                children: <SquadPane squadId={sq} />,
              }))}
            />
          )}
        </Content>
      </Layout>
    </Layout>
  );
}
