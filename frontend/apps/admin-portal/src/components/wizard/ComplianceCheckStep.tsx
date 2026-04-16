import { Alert, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

interface ComplianceRule {
  key: string;
  name: string;
  status: 'pass' | 'fail' | 'warn';
  riskLevel: string;
  remediationUrl: string;
}

const STATUS_CONFIG = {
  pass: { color: 'green', label: '通过' },
  fail: { color: 'red', label: '失败' },
  warn: { color: 'orange', label: '警告' },
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

const columns: ColumnsType<ComplianceRule> = [
  {
    title: '规则名称',
    dataIndex: 'name',
    key: 'name',
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    render: (status: ComplianceRule['status']) => {
      const config = STATUS_CONFIG[status];
      return <Tag color={config.color}>{config.label}</Tag>;
    },
  },
  {
    title: '风险等级',
    dataIndex: 'riskLevel',
    key: 'riskLevel',
  },
  {
    title: '操作',
    key: 'action',
    render: (_: unknown, record: ComplianceRule) => (
      <a href={record.remediationUrl}>修复指南</a>
    ),
  },
];

export function ComplianceCheckStep() {
  const passCount = mockRules.filter((r) => r.status === 'pass').length;
  const warnCount = mockRules.filter((r) => r.status === 'warn').length;
  const failCount = mockRules.filter((r) => r.status === 'fail').length;
  const hasFailures = failCount > 0;

  return (
    <div data-testid="compliance-step">
      <Typography.Text strong data-testid="compliance-summary">
        通过 {passCount}/{mockRules.length} · 警告 {warnCount} · 失败 {failCount}
      </Typography.Text>

      {hasFailures && (
        <Alert
          data-testid="compliance-alert"
          type="error"
          message="存在未通过项，外部访问已阻塞，仅沙箱可用"
          showIcon
          style={{ margin: '16px 0' }}
        />
      )}

      <Table
        data-testid="compliance-table"
        columns={columns}
        dataSource={mockRules}
        pagination={false}
        size="small"
        style={{ marginTop: 16 }}
      />
    </div>
  );
}
