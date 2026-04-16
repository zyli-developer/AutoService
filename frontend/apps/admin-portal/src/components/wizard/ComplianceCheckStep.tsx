interface ComplianceRule {
  key: string;
  name: string;
  status: 'pass' | 'fail' | 'warn';
  riskLevel: string;
  remediationUrl: string;
}

const STATUS_CONFIG = {
  pass: { bg: '#84e7a5', color: '#0a4d28', label: '\u901A\u8FC7' },
  fail: { bg: 'var(--p)', color: '#fff', label: '\u5931\u8D25' },
  warn: { bg: 'var(--l400)', color: 'var(--l800)', label: '\u8B66\u544A' },
} as const;

const mockRules: ComplianceRule[] = [
  { key: 'R01', name: '\u6570\u636E\u52A0\u5BC6\u4F20\u8F93 (TLS 1.2+)', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r01' },
  { key: 'R02', name: '\u9759\u6001\u6570\u636E\u52A0\u5BC6', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r02' },
  { key: 'R03', name: 'API \u8BA4\u8BC1\u673A\u5236', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r03' },
  { key: 'R04', name: '\u8BBF\u95EE\u6743\u9650\u6700\u5C0F\u5316', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r04' },
  { key: 'R05', name: '\u5BA1\u8BA1\u65E5\u5FD7\u5B8C\u6574\u6027', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r05' },
  { key: 'R06', name: '\u5BC6\u94A5\u8F6E\u6362\u7B56\u7565', status: 'warn', riskLevel: '\u4E2D', remediationUrl: '#r06' },
  { key: 'R07', name: '\u8F93\u5165\u9A8C\u8BC1\u4E0E\u8FC7\u6EE4', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r07' },
  { key: 'R08', name: 'SQL \u6CE8\u5165\u9632\u62A4', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r08' },
  { key: 'R09', name: 'XSS \u9632\u62A4', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r09' },
  { key: 'R10', name: 'CSRF \u9632\u62A4', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r10' },
  { key: 'R11', name: '\u901F\u7387\u9650\u5236\u914D\u7F6E', status: 'warn', riskLevel: '\u4F4E', remediationUrl: '#r11' },
  { key: 'R12', name: '\u4F9D\u8D56\u6F0F\u6D1E\u626B\u63CF', status: 'fail', riskLevel: '\u9AD8', remediationUrl: '#r12' },
  { key: 'R13', name: '\u5BB9\u5668\u955C\u50CF\u7B7E\u540D', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r13' },
  { key: 'R14', name: '\u7F51\u7EDC\u9694\u79BB\u7B56\u7565', status: 'pass', riskLevel: '\u9AD8', remediationUrl: '#r14' },
  { key: 'R15', name: '\u4E2A\u4EBA\u6570\u636E\u533F\u540D\u5316', status: 'fail', riskLevel: '\u9AD8', remediationUrl: '#r15' },
  { key: 'R16', name: '\u5907\u4EFD\u4E0E\u6062\u590D\u9A8C\u8BC1', status: 'pass', riskLevel: '\u4E2D', remediationUrl: '#r16' },
];

export function ComplianceCheckStep() {
  const passCount = mockRules.filter((r) => r.status === 'pass').length;
  const warnCount = mockRules.filter((r) => r.status === 'warn').length;
  const failCount = mockRules.filter((r) => r.status === 'fail').length;
  const hasFailures = failCount > 0;

  return (
    <div data-testid="compliance-step">
      <div className="cs-card">
        <div className="cs-ct" data-testid="compliance-summary">
          {'\u901A\u8FC7'} {passCount}/{mockRules.length} {'\u00B7'} {'\u8B66\u544A'} {warnCount} {'\u00B7'} {'\u5931\u8D25'} {failCount}
        </div>

        {hasFailures && (
          <div className="cs-pg warn" data-testid="compliance-alert">
            {'\u5B58\u5728\u672A\u901A\u8FC7\u9879\uFF0C\u5916\u90E8\u8BBF\u95EE\u5DF2\u963B\u585E\uFF0C\u4EC5\u6C99\u7BB1\u53EF\u7528'}
          </div>
        )}

        <div data-testid="compliance-table" style={{ marginTop: 12 }}>
          {mockRules.map((rule) => {
            const cfg = STATUS_CONFIG[rule.status];
            return (
              <div key={rule.key} className="cs-row">
                <span>{rule.name}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: cfg.bg, color: cfg.color, fontWeight: 600 }}>
                    {cfg.label}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--silver)' }}>{rule.riskLevel}</span>
                  <a href={rule.remediationUrl} style={{ fontSize: 11, color: 'var(--m600)' }}>
                    {'\u4FEE\u590D\u6307\u5357'}
                  </a>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
