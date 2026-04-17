const STEPS = ['上传', '权限', '预演', '合规', '可用'];

interface WizardStepperProps {
  currentStep: number;
}

export function WizardStepper({ currentStep }: WizardStepperProps) {
  return (
    <div className="cs-wiz" data-testid="wizard-stepper">
      {STEPS.map((label, i) => {
        let cls = '';
        if (i < currentStep) cls = 'done';
        else if (i === currentStep) cls = 'cur';
        return (
          <span key={i}>
            <span className={`cs-wiz-step ${cls}`} data-testid={`wiz-step-${i}`}>
              {i + 1}.{label}
            </span>
            {i < STEPS.length - 1 && <span className="cs-arr"> {'›'} </span>}
          </span>
        );
      })}
    </div>
  );
}
