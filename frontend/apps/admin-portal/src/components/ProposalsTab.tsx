import { useEffect, useState } from 'react';
import { Button, Card, Select, Space, Spin, Statistic, Tag, Typography, Row, Col } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { useAdminStore } from '../store/adminStore';
import type { ProposalUI } from '../store/adminStore';

const CATEGORIES = ['response_quality', 'workflow', 'knowledge_gap', 'tone'] as const;
const STATUSES = ['draft', 'accepted', 'rejected', 'implemented'] as const;

const CATEGORY_LABELS: Record<string, string> = {
  response_quality: '回复质量',
  workflow: '工作流程',
  knowledge_gap: '知识缺口',
  tone: '语气风格',
};

const PRIORITY_COLORS: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
};

const STATUS_LABELS: Record<string, string> = {
  draft: '待审核',
  accepted: '已接受',
  rejected: '已拒绝',
  implemented: '已实施',
};

function mockLoadProposals(): Promise<ProposalUI[]> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const proposals: ProposalUI[] = [];
      const cats = [...CATEGORIES];
      const priorities: Array<'high' | 'medium' | 'low'> = ['high', 'medium', 'low'];
      for (let i = 0; i < 6; i++) {
        proposals.push({
          id: `prop_${String(i + 1).padStart(3, '0')}`,
          created_at: new Date(Date.now() - i * 3600000).toISOString(),
          category: cats[i % cats.length],
          title: `改进建议 #${i + 1}`,
          description: `基于最近 ${(i + 1) * 5} 条对话分析得出的改进方向。`,
          suggestion: `建议优化 ${CATEGORY_LABELS[cats[i % cats.length]]} 相关配置。`,
          priority: priorities[i % priorities.length],
          status: 'draft',
          source_conversations: [`conv_${i * 2 + 1}`, `conv_${i * 2 + 2}`],
          evidence: i % 2 === 0 ? ['证据片段A', '证据片段B'] : [],
          compliance_check: { passed: true, flags: [] },
        });
      }
      resolve(proposals);
    }, 800);
  });
}

export function ProposalsTab() {
  const { proposals, proposalsLoading, setProposals, setProposalsLoading, updateProposalStatus } =
    useAdminStore();
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  useEffect(() => {
    if (proposals.length === 0 && !proposalsLoading) {
      setProposalsLoading(true);
      mockLoadProposals().then((data) => {
        setProposals(data);
        setProposalsLoading(false);
      });
    }
  }, []);

  const filtered = proposals.filter((p) => {
    if (statusFilter && p.status !== statusFilter) return false;
    if (categoryFilter && p.category !== categoryFilter) return false;
    return true;
  });

  const draftCount = proposals.filter((p) => p.status === 'draft').length;
  const acceptedCount = proposals.filter((p) => p.status === 'accepted').length;
  const rejectedCount = proposals.filter((p) => p.status === 'rejected').length;

  return (
    <div data-testid="tab-proposals">
      <Typography.Title level={4}>提案审核</Typography.Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Statistic title="待审核" value={draftCount} data-testid="stat-draft" />
        </Col>
        <Col span={8}>
          <Statistic title="已接受" value={acceptedCount} data-testid="stat-accepted" />
        </Col>
        <Col span={8}>
          <Statistic title="已拒绝" value={rejectedCount} data-testid="stat-rejected" />
        </Col>
      </Row>

      <Space style={{ marginBottom: 16 }} data-testid="proposal-filters">
        <Select
          allowClear
          placeholder="按状态筛选"
          data-testid="filter-status"
          style={{ width: 150 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v || null)}
          options={STATUSES.map((s) => ({ label: STATUS_LABELS[s], value: s }))}
        />
        <Select
          allowClear
          placeholder="按分类筛选"
          data-testid="filter-category"
          style={{ width: 150 }}
          value={categoryFilter}
          onChange={(v) => setCategoryFilter(v || null)}
          options={CATEGORIES.map((c) => ({ label: CATEGORY_LABELS[c], value: c }))}
        />
      </Space>

      {proposalsLoading && (
        <div data-testid="proposals-loading">
          <Spin tip="加载提案..." />
        </div>
      )}

      <div data-testid="proposal-list">
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {filtered.map((proposal) => (
            <Card
              key={proposal.id}
              size="small"
              data-testid={`proposal-card-${proposal.id}`}
              title={
                <Space>
                  <span>{proposal.title}</span>
                  <Tag color={PRIORITY_COLORS[proposal.priority]} data-testid={`priority-tag-${proposal.id}`}>
                    {proposal.priority}
                  </Tag>
                  <Tag>{CATEGORY_LABELS[proposal.category]}</Tag>
                  <Tag color={proposal.status === 'accepted' ? 'green' : proposal.status === 'rejected' ? 'red' : 'default'}>
                    {STATUS_LABELS[proposal.status]}
                  </Tag>
                </Space>
              }
              extra={
                proposal.status === 'draft' ? (
                  <Space>
                    <Button
                      size="small"
                      type="primary"
                      data-testid={`btn-accept-${proposal.id}`}
                      icon={<CheckCircleOutlined />}
                      onClick={() => updateProposalStatus(proposal.id, 'accepted')}
                    >
                      接受
                    </Button>
                    <Button
                      size="small"
                      danger
                      data-testid={`btn-reject-${proposal.id}`}
                      icon={<CloseCircleOutlined />}
                      onClick={() => updateProposalStatus(proposal.id, 'rejected')}
                    >
                      拒绝
                    </Button>
                  </Space>
                ) : null
              }
            >
              <Typography.Paragraph>{proposal.description}</Typography.Paragraph>
              <Typography.Text type="secondary">建议：</Typography.Text>
              <Typography.Paragraph>{proposal.suggestion}</Typography.Paragraph>
              {proposal.evidence.length > 0 && (
                <div data-testid={`evidence-${proposal.id}`}>
                  <Typography.Text type="secondary">证据：</Typography.Text>
                  {proposal.evidence.map((e, idx) => (
                    <Tag key={idx} style={{ marginTop: 4 }}>{e}</Tag>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </Space>
      </div>
    </div>
  );
}
