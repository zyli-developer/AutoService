import { useState } from 'react';
import { List, Tag, Typography, Input, Button, Space, Empty } from 'antd';
import {
  BellOutlined,
  InfoCircleOutlined,
  CodeOutlined,
} from '@ant-design/icons';
import { useAdminStore, Notification } from '../store/adminStore';

const typeConfig: Record<Notification['type'], { color: string; label: string; icon: React.ReactNode }> = {
  alert: { color: 'red', label: '告警', icon: <BellOutlined /> },
  info: { color: 'blue', label: '信息', icon: <InfoCircleOutlined /> },
  command: { color: 'green', label: '命令', icon: <CodeOutlined /> },
};

function makeId(): string {
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const commandHandlers: Record<string, () => Pick<Notification, 'title' | 'description' | 'type'>> = {
  '/rules': () => ({ type: 'command', title: '规则配置已更新', description: '已执行 /rules 命令' }),
  '/status': () => ({ type: 'command', title: '系统状态：正常', description: '已执行 /status 命令' }),
  '/review': () => ({ type: 'command', title: '审查已启动', description: '已执行 /review 命令' }),
};

export function NotificationsTab() {
  const [input, setInput] = useState('');
  const notifications = useAdminStore((s) => s.notifications);
  const addNotification = useAdminStore((s) => s.addNotification);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const handler = commandHandlers[trimmed];
    if (handler) {
      const result = handler();
      addNotification({
        id: makeId(),
        ts: new Date().toISOString(),
        ...result,
      });
    } else {
      addNotification({
        id: makeId(),
        type: 'info',
        title: trimmed,
        description: '用户输入',
        ts: new Date().toISOString(),
      });
    }
    setInput('');
  };

  return (
    <div data-testid="tab-notifications">
      <Typography.Title level={4}>通知中心</Typography.Title>

      <div data-testid="notification-list">
        {notifications.length === 0 ? (
          <Empty description="暂无通知" />
        ) : (
          <List
            dataSource={notifications}
            renderItem={(item) => {
              const cfg = typeConfig[item.type];
              return (
                <List.Item data-testid={`notification-item-${item.id}`}>
                  <List.Item.Meta
                    avatar={cfg.icon}
                    title={
                      <Space>
                        <Tag color={cfg.color}>{cfg.label}</Tag>
                        <Typography.Text strong>{item.title}</Typography.Text>
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={0}>
                        <Typography.Text type="secondary">{item.description}</Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {item.ts}
                        </Typography.Text>
                      </Space>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </div>

      <Space.Compact style={{ width: '100%', marginTop: 16 }}>
        <Input
          data-testid="notification-input"
          placeholder="输入命令：/rules, /status, /review"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={handleSend}
        />
        <Button data-testid="notification-send" type="primary" onClick={handleSend}>
          发送
        </Button>
      </Space.Compact>
    </div>
  );
}
