interface ComplianceRule {
  key: string;
  name: string;
  status: 'pass' | 'fail' | 'warn';
  riskLevel: string;
  remediationUrl: string;
}

const STATUS_CONFIG = {
  pass: { bg: '#84e7a5', color: '#0a4d28', label: '通过' },
  fail: { bg: 'var(--p)', color: '#fff', label: '失败' },
  warn: { bg: 'var(--l400)', color: 'var(--l800)', label: '警告' },
} as const;

const mockRules: ComplianceRule[] = [
  { key: 'R01', name: '数据加密传输 (TLS 1.2+)', status: 'pass', riskLevel: '高', remediationUrl: '#r01' },
  { key: 'R02', name: '静态数据加密', status: 'pass', riskLevel: '高', remediationUrl: '#r02' },
  { key: 'R03', name: 'API 认证机制', status: 'pass', riskLevel: '高', remediationUrl: '#r03' },
  { key: 'R04', name: '访问权限最小化', status: 'pass', riskLevel: '中', remediationUrl: '#r04' },
  { key: 'R05', name: '审计日志完整性', status: 'pass', riskLevel: '中', remediationUrl: '#r05' },
  { key: 'R06', name: '密钥轮换策略', status: 'warn', riskLevel: '中', remediationUrl: '#r06' },
  { key: 'R07', name: '输入验证与过滤', status: 'pass', riskLevel: '高', remediationUrl: '#r07' },
  { key: 'R08', name: 'SQL 注入防护', status: 'pass', riskLevel: '高', remediationUrl: '#r08' },
  { key: 'R09', name: 'XSS 防护', status: 'pass', riskLevel: '中', remediationUrl: '#r09' },
  { key: 'R10', name: 'CSRF 防护', status: 'pass', riskLevel: '中', remediationUrl: '#r10' },
  { key: 'R11', name: '速率限制配置', status: 'warn', riskLevel: '低', remediationUrl: '#r11' },
  { key: 'R12', name: '依赖漏洞扫描', status: 'fail', riskLevel: '高', remediationUrl: '#r12' },
  { key: 'R13', name: '容器镜像签名', status: 'pass', riskLevel: '中', remediationUrl: '#r13' },
  { key: 'R14', name: '网络隔离策略', status: 'pass', riskLevel: '高', remediationUrl: '#r14' },
  { key: 'R15', name: '个人数据匿名化', status: 'fail', riskLevel: '高', remediationUrl: '#r15' },
  { key: 'R16', name: '备份与恢复验证', status: 'pass', riskLevel: '中', remediationUrl: '#r16' },
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
          {'通过'} {passCount}/{mockRules.length} {'·'} {'警告'} {warnCount} {'·'} {'失败'} {failCount}
        </div>

        {hasFailures && (
          <div className="cs-pg warn" data-testid="compliance-alert">
            {'存在未通过项，外部访问已阻塞，仅沙箱可用'}
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
                    {'修复指南'}
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
