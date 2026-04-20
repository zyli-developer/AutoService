import { useTranslation } from '@autoservice/i18n';

const STEP_KEYS = [
  'admin.wizard.step.1',
  'admin.wizard.step.2',
  'admin.wizard.step.3',
  'admin.wizard.step.4',
  'admin.wizard.step.5',
];

interface WizardStepperProps {
  currentStep: number;
}

export function WizardStepper({ currentStep }: WizardStepperProps) {
  const { t } = useTranslation();
  return (
    <div className="cs-wiz" data-testid="wizard-stepper">
      {STEP_KEYS.map((key, i) => {
        let cls = '';
        if (i < currentStep) cls = 'done';
        else if (i === currentStep) cls = 'cur';
        return (
          <span key={i}>
            <span className={`cs-wiz-step ${cls}`} data-testid={`wiz-step-${i}`}>
              {t(key)}
            </span>
            {i < STEP_KEYS.length - 1 && <span className="cs-arr"> {'›'} </span>}
          </span>
        );
      })}
    </div>
  );
}
