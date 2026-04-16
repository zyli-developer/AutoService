const STEPS = ['\u4E0A\u4F20', '\u6743\u9650', '\u9884\u6F14', '\u5408\u89C4', '\u53EF\u7528'];

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
