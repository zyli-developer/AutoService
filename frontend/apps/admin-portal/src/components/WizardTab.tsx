import { useAdminStore } from '../store/adminStore';
import { MaterialUploadStep } from './wizard/MaterialUploadStep';
import { ChannelConfigStep } from './wizard/ChannelConfigStep';
import { VirtualRehearsalStep } from './wizard/VirtualRehearsalStep';
import { ComplianceCheckStep } from './wizard/ComplianceCheckStep';

const STEPS = ['上传', '权限', '预演', '合规', '可用'] as const;

function SandboxReady() {
  const tenantId = useAdminStore((s) => s.tenantId);
  return (
    <div className="cs-card hl">
      <div className="cs-ct">🎉 沙箱可用</div>
      <div className="cs-row"><span>沙箱 URL</span><span style={{ color: 'var(--m600)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{tenantId}.sandbox.onesync</span></div>
      <div className="cs-row"><span>团队成员</span><span style={{ color: '#000' }}>已邀请 5 人</span></div>
      <div className="cs-row"><span>对外开放</span><span style={{ color: 'var(--l700)', fontWeight: 700 }}>待商户决定</span></div>
      <div className="cs-pg ok">✓ 准备好后一键对外</div>
    </div>
  );
}

export function WizardTab() {
  const { tenantId, wizardStep, setWizardStep } = useAdminStore();

  return (
    <div data-testid="tab-wizard">
      <div className="cs-wiz" data-testid="wizard-stepper">
        {STEPS.map((name, i) => (
          <span key={i}>
            <span
              className={`cs-wiz-step ${i < wizardStep ? 'done' : i === wizardStep ? 'cur' : ''}`}
              data-testid={`wiz-step-${i}`}
              onClick={() => i <= wizardStep && setWizardStep(i)}
              style={{ cursor: i <= wizardStep ? 'pointer' : 'default' }}
            >
              {i + 1}.{name}
            </span>
            {i < STEPS.length - 1 && <span className="cs-arr">›</span>}
          </span>
        ))}
      </div>

      <div style={{ marginTop: 16 }}>
        {wizardStep === 0 && <MaterialUploadStep tenantId={tenantId || 'default'} onGenerated={() => setWizardStep(1)} />}
        {wizardStep === 1 && <ChannelConfigStep tenantId={tenantId || 'default'} />}
        {wizardStep === 2 && <VirtualRehearsalStep tenantId={tenantId || 'default'} />}
        {wizardStep === 3 && <ComplianceCheckStep />}
        {wizardStep === 4 && <SandboxReady />}
      </div>

      <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        {wizardStep > 0 && (
          <button className="cs-btn" onClick={() => setWizardStep(wizardStep - 1)}>上一步</button>
        )}
        {wizardStep < STEPS.length - 1 && (
          <button className="cs-btn ok" onClick={() => setWizardStep(wizardStep + 1)} data-testid="wizard-next">下一步</button>
        )}
      </div>
    </div>
  );
}
