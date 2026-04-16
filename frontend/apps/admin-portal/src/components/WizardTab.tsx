import { Steps, Typography } from 'antd';
import { useAdminStore } from '../store/adminStore';
import { MaterialUploadStep } from './wizard/MaterialUploadStep';
import { ChannelConfigStep } from './wizard/ChannelConfigStep';
import { ComplianceCheckStep } from './wizard/ComplianceCheckStep';

export function WizardTab() {
  const { tenantId, wizardStep, setWizardStep } = useAdminStore();

  const steps = [
    { title: '资料上传', description: 'Step 1' },
    { title: '渠道配置', description: 'Step 2' },
    { title: '虚拟预演', description: 'Step 3' },
    { title: '合规预检', description: 'Step 4' },
  ];

  return (
    <div data-testid="tab-wizard">
      <Typography.Title level={4}>设置向导</Typography.Title>
      <Steps
        current={wizardStep}
        items={steps}
        onChange={(step) => setWizardStep(step)}
        style={{ marginBottom: 24 }}
      />
      {wizardStep === 0 && (
        <MaterialUploadStep
          tenantId={tenantId || 'default'}
          onGenerated={() => setWizardStep(1)}
        />
      )}
      {wizardStep === 1 && (
        <ChannelConfigStep tenantId={tenantId || 'default'} />
      )}
      {wizardStep === 2 && (
        <Typography.Paragraph type="secondary">
          虚拟预演 — T3B.4 TODO
        </Typography.Paragraph>
      )}
      {wizardStep === 3 && (
        <ComplianceCheckStep />
      )}
    </div>
  );
}
