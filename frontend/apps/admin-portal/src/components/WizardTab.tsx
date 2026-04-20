import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../store/adminStore';
import { MaterialUploadStep } from './wizard/MaterialUploadStep';
import { ChannelConfigStep } from './wizard/ChannelConfigStep';
import { VirtualRehearsalStep } from './wizard/VirtualRehearsalStep';
import { ComplianceCheckStep } from './wizard/ComplianceCheckStep';
import { SandboxReady } from './wizard/SandboxReady';

const STEP_KEYS = [
  'admin.wizard.step.1',
  'admin.wizard.step.2',
  'admin.wizard.step.3',
  'admin.wizard.step.4',
  'admin.wizard.step.5',
] as const;

/** Check whether the given wizard step is considered complete. */
function useStepComplete(step: number): boolean {
  const generationResult = useAdminStore((s) => s.generationResult);
  const rehearsalDialogs = useAdminStore((s) => s.rehearsalDialogs);

  switch (step) {
    // Step 0 (Upload): agents must have been generated
    case 0:
      return generationResult !== null;
    // Step 1 (Channel): always completable (channel defaults to 'web' selected)
    case 1:
      return true;
    // Step 2 (Rehearsal): all dialogs must be reviewed (none pending)
    case 2:
      return (
        rehearsalDialogs.length > 0 &&
        rehearsalDialogs.every((d) => d.review_status !== 'pending')
      );
    // Step 3 (Compliance): no gate — can proceed with warnings per PRD
    case 3:
      return true;
    default:
      return true;
  }
}

export function WizardTab() {
  const { t } = useTranslation();
  const { tenantId, wizardStep, setWizardStep } = useAdminStore();
  const currentStepComplete = useStepComplete(wizardStep);

  return (
    <div data-testid="tab-wizard">
      <div className="cs-wiz" data-testid="wizard-stepper">
        {STEP_KEYS.map((key, i) => (
          <span key={i}>
            <span
              className={`cs-wiz-step ${i < wizardStep ? 'done' : i === wizardStep ? 'cur' : ''}`}
              data-testid={`wiz-step-${i}`}
              onClick={() => i <= wizardStep && setWizardStep(i)}
              style={{ cursor: i <= wizardStep ? 'pointer' : 'default' }}
            >
              {t(key)}
            </span>
            {i < STEP_KEYS.length - 1 && <span className="cs-arr">›</span>}
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
          <button className="cs-btn" onClick={() => setWizardStep(wizardStep - 1)}>{t('common.previous')}</button>
        )}
        {wizardStep < STEP_KEYS.length - 1 && (
          <button
            className="cs-btn ok"
            onClick={() => setWizardStep(wizardStep + 1)}
            disabled={!currentStepComplete}
            data-testid="wizard-next"
            title={currentStepComplete ? undefined : t('admin.wizard.complete_current_first')}
            style={currentStepComplete ? undefined : { opacity: 0.5, cursor: 'not-allowed' }}
          >
            {t('common.next')}
          </button>
        )}
      </div>
    </div>
  );
}
