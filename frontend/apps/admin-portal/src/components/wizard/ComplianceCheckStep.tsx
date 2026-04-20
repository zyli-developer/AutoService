import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { postJSON } from '../../api';
import { useAdminStore } from '../../store/adminStore';

interface ComplianceResult {
  rule_id: string;
  name: string;
  severity: string;
  passed: boolean;
  field: string;
  remediation_doc: string;
}

interface ComplianceReport {
  tenant_id: string;
  risk_level: string;
  total_rules: number;
  passed: number;
  failed: number;
  pass_rate: number;
  results: ComplianceResult[];
}

export function ComplianceCheckStep() {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    postJSON<ComplianceReport>(`/api/compliance/check?tenant_id=${encodeURIComponent(tenantId)}`)
      .then(setReport)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tenantId]);

  if (loading) return <div className="im-empty">{t('admin.wizard.compliance.loading')}</div>;
  if (!report) return <div className="cs-pg warn">{t('admin.wizard.compliance.error')}</div>;

  return (
    <div data-testid="compliance-step">
      <div className="cs-card hl">
        <div className="cs-ct" data-testid="compliance-summary">
          <span className="num">4</span>合规预检 · 风险: {report.risk_level}
        </div>
        <div className="cs-row">
          <span>通过 / 总数</span>
          <span style={{ color: 'var(--m600)', fontWeight: 700 }}>{report.passed} / {report.total_rules}</span>
        </div>
        <div className="cs-row">
          <span>通过率</span>
          <span style={{ fontWeight: 700 }}>{(report.pass_rate * 100).toFixed(0)}%</span>
        </div>
        {report.failed > 0 && (
          <div className="cs-pg warn" data-testid="compliance-alert">
            ⚠ {report.failed} 项未通过，外部访问阻塞，仅沙箱可用
          </div>
        )}
      </div>

      <div className="cs-card" style={{ marginTop: 14 }}>
        <div className="cs-ct">📋 {report.total_rules} 条规则（来自 /api/compliance/check）</div>
        <div data-testid="compliance-table">
          {report.results.map((rule) => (
            <div key={rule.rule_id} className="cs-row">
              <span>{rule.name}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                  background: rule.passed ? '#84e7a5' : 'var(--p)',
                  color: rule.passed ? '#0a4d28' : '#fff',
                }}>
                  {rule.passed ? '通过' : '失败'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--silver)' }}>{rule.severity}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
