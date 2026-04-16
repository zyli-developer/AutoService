import { Typography } from 'antd';

export function NotificationsTab() {
  return (
    <div data-testid="tab-notifications">
      <Typography.Title level={4}>通知中心</Typography.Title>
      <Typography.Paragraph type="secondary">
        通知内容 — T3B.7 TODO
      </Typography.Paragraph>
    </div>
  );
}
