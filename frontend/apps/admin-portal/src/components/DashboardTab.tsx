import { Typography } from 'antd';

export function DashboardTab() {
  return (
    <div data-testid="tab-dashboard">
      <Typography.Title level={4}>运营仪表盘</Typography.Title>
      <Typography.Paragraph type="secondary">
        仪表盘内容 — T3B.6 TODO
      </Typography.Paragraph>
    </div>
  );
}
