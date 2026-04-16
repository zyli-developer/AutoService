import { useEffect, useState } from 'react';
import { useAdminStore } from '../store/adminStore';
import type { ProposalUI } from '../store/adminStore';

const CATEGORY_LABELS: Record<string, string> = {
  response_quality: '回复质量',
  workflow: '工作流程',
  knowledge_gap: '知识缺口',
  tone: '语气风格',
};

const PRIORITY_STYLES: Record<string, { bg: string; color: string }> = {
  high: { bg: 'var(--p)', color: '#fff' },
  medium: { bg: 'var(--l500)', color: 'var(--l800)' },
  low: { bg: 'var(--m300)', color: 'var(--m800)' },
};

const STATUS_LABELS: Record<string, string> = {
  draft: '待审核', accepted: '已接受', rejected: '已拒绝', implemented: '已实施',
};

function mockLoadProposals(): Promise<ProposalUI[]> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const cats = ['response_quality', 'workflow', 'knowledge_gap', 'tone'];
      const pris: Array<'high' | 'medium' | 'low'> = ['high', 'medium', 'low'];
      resolve(
        Array.from({ length: 6 }, (_, i) => ({
          id: `prop_${String(i + 1).padStart(3, '0')}`,
          created_at: new Date(Date.now() - i * 3600000).toISOString(),
          category: cats[i % cats.length],
          title: `改进建议 #${i + 1}`,
          description: `基于最近 ${(i + 1) * 5} 条对话分析得出`,
          suggestion: `建议优化 ${CATEGORY_LABELS[cats[i % cats.length]]} 相关配置`,
          priority: pris[i % pris.length],
          status: 'draft' as const,
          source_conversations: [`conv_${i * 2 + 1}`, `conv_${i * 2 + 2}`],
          evidence: i % 2 === 0 ? ['证据片段A', '证据片段B'] : [],
          compliance_check: { passed: true, flags: [] },
        })),
      );
    }, 500);
  });
}

export function ProposalsTab() {
  const { proposals, proposalsLoading, setProposals, setProposalsLoading, updateProposalStatus } = useAdminStore();
  const [statusFilter, setStatusFilter] = useState<string>('');

  useEffect(() => {
    if (proposals.length === 0 && !proposalsLoading) {
      setProposalsLoading(true);
      mockLoadProposals().then((data) => {
        setProposals(data);
        setProposalsLoading(false);
      });
    }
  }, []);

  const filtered = proposals.filter((p) => !statusFilter || p.status === statusFilter);
  const draftCount = proposals.filter((p) => p.status === 'draft').length;
  const acceptedCount = proposals.filter((p) => p.status === 'accepted').length;

  return (
    <div data-testid="tab-proposals">
      {/* Stats */}
      <div className="cs-card" style={{ marginBottom: 14 }}>
        <div className="cs-ct">📊 提案统计</div>
        <div className="cs-row"><span>待审核</span><span style={{ color: 'var(--l700)', fontWeight: 700 }} data-testid="stat-draft">{draftCount}</span></div>
        <div className="cs-row"><span>已接受</span><span style={{ color: 'var(--m600)', fontWeight: 700 }} data-testid="stat-accepted">{acceptedCount}</span></div>
      </div>

      {/* Filter */}
      <div style={{ marginBottom: 12, display: 'flex', gap: 6 }} data-testid="proposal-filters">
        {['', 'draft', 'accepted', 'rejected'].map((s) => (
          <button
            key={s}
            className={`cs-wiz-step ${statusFilter === s ? 'cur' : ''}`}
            onClick={() => setStatusFilter(s)}
            data-testid={s ? `filter-${s}` : 'filter-all'}
          >
            {s ? STATUS_LABELS[s] : '全部'}
          </button>
        ))}
      </div>

      {proposalsLoading && <div className="im-empty" data-testid="proposals-loading">加载提案...</div>}

      {/* Proposal Cards */}
      <div data-testid="proposal-list" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {filtered.map((p) => {
          const priStyle = PRIORITY_STYLES[p.priority] || PRIORITY_STYLES.low;
          return (
            <div key={p.id} className="im-card" data-testid={`proposal-card-${p.id}`}>
              <div className="im-avatar a1" style={{ background: priStyle.bg, color: priStyle.color, fontSize: 10 }}>
                {p.priority.charAt(0).toUpperCase()}
              </div>
              <div className="im-msg-body">
                <div className="im-msg-meta">
                  <span className="im-msg-author">{p.title}</span>
                  <span
                    data-testid={`priority-tag-${p.id}`}
                    style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: priStyle.bg, color: priStyle.color, fontWeight: 600,
                    }}
                  >
                    {p.priority}
                  </span>
                  <span className="im-msg-time">{CATEGORY_LABELS[p.category]}</span>
                </div>
                <div className={`im-block ${p.status === 'draft' ? 'highlight' : ''}`}>
                  <div className="im-block-title">
                    {p.description}
                    <span className="im-block-status">{STATUS_LABELS[p.status]}</span>
                  </div>
                  <div className="im-block-meta">{p.suggestion}</div>
                  {p.evidence.length > 0 && (
                    <div className="im-block-meta" data-testid={`evidence-${p.id}`} style={{ marginTop: 4 }}>
                      证据: {p.evidence.join(', ')}
                    </div>
                  )}
                </div>
                {p.status === 'draft' && (
                  <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
                    <button className="cs-btn ok" data-testid={`btn-accept-${p.id}`} onClick={() => updateProposalStatus(p.id, 'accepted')}>✓ 接受</button>
                    <button className="cs-btn" data-testid={`btn-reject-${p.id}`} onClick={() => updateProposalStatus(p.id, 'rejected')} style={{ background: 'var(--p)', color: '#fff' }}>✗ 拒绝</button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
