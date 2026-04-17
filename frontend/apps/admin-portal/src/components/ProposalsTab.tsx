import { useEffect, useState } from 'react';
import { fetchJSON, postJSON } from '../api';

interface Proposal {
  id: string;
  created_at: string;
  category: string;
  title: string;
  priority: string;
  status: string;
  suggestion?: string;
  source_conversations?: string[];
  compliance_status?: string;
}

const PRIORITY_STYLES: Record<string, { bg: string; color: string }> = {
  high: { bg: 'var(--p)', color: '#fff' },
  medium: { bg: 'var(--l500)', color: 'var(--l800)' },
  low: { bg: 'var(--m300)', color: 'var(--m800)' },
};

const STATUS_LABELS: Record<string, string> = {
  draft: '待审核', accepted: '已接受', rejected: '已拒绝', blocked: '已阻止',
};

export function ProposalsTab() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');

  const load = () => {
    setLoading(true);
    fetchJSON<Proposal[]>('/api/proposals')
      .then(setProposals)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleGenerate = () => {
    setGenerating(true);
    postJSON<Proposal[]>('/api/proposals/run')
      .then((newProps) => { setProposals((prev) => [...newProps, ...prev]); })
      .catch(() => {})
      .finally(() => setGenerating(false));
  };

  const filtered = proposals.filter((p) => !statusFilter || p.status === statusFilter);

  return (
    <div data-testid="tab-proposals">
      <div className="cs-card" style={{ marginBottom: 14 }}>
        <div className="cs-ct">📊 提案（来自 /api/proposals）</div>
        <div className="cs-row">
          <span>总数</span>
          <span style={{ fontWeight: 700 }} data-testid="stat-draft">{proposals.length}</span>
        </div>
        <button className="cs-btn ok" onClick={handleGenerate} disabled={generating} style={{ marginTop: 8, opacity: generating ? 0.6 : 1 }}>
          {generating ? '生成中...' : '🔄 运行 Pipeline'}
        </button>
      </div>

      <div style={{ marginBottom: 12, display: 'flex', gap: 6 }} data-testid="proposal-filters">
        {['', 'draft', 'accepted', 'rejected', 'blocked'].map((s) => (
          <button key={s} className={`cs-wiz-step ${statusFilter === s ? 'cur' : ''}`} onClick={() => setStatusFilter(s)}>
            {s ? STATUS_LABELS[s] || s : '全部'}
          </button>
        ))}
      </div>

      {loading && <div className="im-empty" data-testid="proposals-loading">加载中...</div>}

      {!loading && filtered.length === 0 && (
        <div className="im-empty">暂无提案，点击"运行 Pipeline"生成</div>
      )}

      <div data-testid="proposal-list" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {filtered.map((p) => {
          const priStyle = PRIORITY_STYLES[p.priority] || PRIORITY_STYLES.low;
          return (
            <div key={p.id} className="im-card" data-testid={`proposal-card-${p.id}`}>
              <div className="im-avatar a1" style={{ background: priStyle.bg, color: priStyle.color, fontSize: 10 }}>
                {(p.priority || 'L').charAt(0).toUpperCase()}
              </div>
              <div className="im-msg-body">
                <div className="im-msg-meta">
                  <span className="im-msg-author">{p.title || p.id}</span>
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: priStyle.bg, color: priStyle.color, fontWeight: 600 }}>
                    {p.priority}
                  </span>
                  <span className="im-msg-time">{p.category}</span>
                </div>
                <div className={`im-block ${p.status === 'draft' ? 'highlight' : ''}`}>
                  <div className="im-block-title">
                    {p.suggestion || p.title}
                    <span className="im-block-status">{STATUS_LABELS[p.status] || p.status}</span>
                  </div>
                  {p.compliance_status && (
                    <div className="im-block-meta">合规: {p.compliance_status}</div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
