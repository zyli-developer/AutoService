import { WizardStepper } from './wizard/WizardStepper';

export function WizardTab() {
  return (
    <div data-testid="tab-wizard">
      <WizardStepper currentStep={0} />

      <div className="cs-card hl">
        <div className="cs-ct">
          <span className="num">1</span>
          {'\u4E0A\u4F20\u57FA\u7840\u4FE1\u606F'}
        </div>
        <div className="cs-row">
          <span>{'\uD83D\uDCC4 \u516C\u53F8\u5B98\u7F51 URL'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
        <div className="cs-row">
          <span>{'\uD83D\uDCCB \u4EA7\u54C1\u76EE\u5F55.pdf'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
        <div className="cs-row">
          <span>{'\uD83D\uDCAC \u5386\u53F2\u5BF9\u8BDD.csv'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
      </div>

      <div className="cs-card">
        <div className="cs-ct">{'\uD83E\uDD16 Agent \u521D\u59CB\u5316'}</div>
        <div className="cs-row">
          <span>{'\u5BA2\u670D Agent'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
        <div className="cs-row">
          <span>{'\u7FFB\u8BD1 Agent'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
        <div className="cs-row">
          <span>{'\u7EBF\u7D22\u6536\u96C6 Agent'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
        <div className="cs-row">
          <span>{'\u667A\u80FD\u5206\u6D41 Agent'}</span>
          <span className="ck">{'\u2713'}</span>
        </div>
      </div>

      <div className="cs-pg">
        {'~15 min \u00B7 \u57FA\u4E8E\u516C\u53F8\u8D44\u6599\u751F\u6210\u4E13\u5C5E Agent'}
      </div>
    </div>
  );
}
