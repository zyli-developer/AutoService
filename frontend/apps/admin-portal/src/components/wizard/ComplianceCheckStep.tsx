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
          <span className="num">4</span>{t('admin.wizard.compliance.title', { risk: report.risk_level })}
        </div>
        <div className="cs-row">
          <span>{t('admin.wizard.compliance.pass_count')}</span>
          <span style={{ color: 'var(--m600)', fontWeight: 700 }}>{report.passed} / {report.total_rules}</span>
        </div>
        <div className="cs-row">
          <span>{t('admin.wizard.compliance.pass_rate')}</span>
          <span style={{ fontWeight: 700 }}>{(report.pass_rate * 100).toFixed(0)}%</span>
        </div>
        {report.failed > 0 && (
          <div className="cs-pg warn" data-testid="compliance-alert">
            ⚠ {t('admin.wizard.compliance.failed_alert', { count: report.failed })}
          </div>
        )}
      </div>

      <div className="cs-card" style={{ marginTop: 14 }}>
        <div className="cs-ct">📋 {t('admin.wizard.compliance.rules_total', { count: report.total_rules })}</div>
        <div data-testid="compliance-table">
          {report.results.map((rule) => (
            <div key={rule.rule_id} className="cs-row">
              <span>{rule.name}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                  background: rule.passed ? 'var(--spring-200)' : 'var(--vermillion-500)',
                  color: rule.passed ? 'var(--spring-900)' : '#fff',
                }}>
                  {rule.passed ? t('admin.wizard.compliance.passed') : t('admin.wizard.compliance.failed')}
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
