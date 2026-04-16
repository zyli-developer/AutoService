import { Typography } from 'antd';

export function ProposalsTab() {
  return (
    <div data-testid="tab-proposals">
      <Typography.Title level={4}>提案审核</Typography.Title>
      <Typography.Paragraph type="secondary">
        提案内容 — T4B.1 TODO
      </Typography.Paragraph>
    </div>
  );
}
