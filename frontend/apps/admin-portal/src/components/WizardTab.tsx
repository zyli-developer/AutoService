import { Steps, Typography } from 'antd';

export function WizardTab() {
  return (
    <div data-testid="tab-wizard">
      <Typography.Title level={4}>设置向导</Typography.Title>
      <Steps
        current={0}
        items={[
          { title: '资料上传', description: 'T3B.2' },
          { title: '渠道配置', description: 'T3B.3' },
          { title: '虚拟预演', description: 'T3B.4' },
          { title: '合规预检', description: 'T3B.5' },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 24 }}>
        向导内容 — T3B.2-5 TODO
      </Typography.Paragraph>
    </div>
  );
}
