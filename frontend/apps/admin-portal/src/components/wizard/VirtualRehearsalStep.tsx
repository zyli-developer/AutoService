import { useEffect } from 'react';
import { useAdminStore } from '../../store/adminStore';
import type { SimDialogUI, SimTurnUI } from '../../store/adminStore';
import { postJSON } from '../../api';

const PERSONAS = [
  { id: 'angry-refund', name_zh: '愤怒退款客户', traits: ['情绪激动', '用词尖锐'], communication_style: 'aggressive' },
  { id: 'price-sensitive', name_zh: '价格敏感客户', traits: ['反复询价', '比较竞品'], communication_style: 'cautious' },
  { id: 'non-native', name_zh: '非母语客户', traits: ['语法不规范', '用词简单'], communication_style: 'hesitant' },
  { id: 'tech-illiterate', name_zh: '技术小白', traits: ['描述模糊', '不懂术语'], communication_style: 'confused' },
] as const;

const SCENARIOS = [
  { id: 'greeting', name_zh: '通用问候', intent: 'general_question', trap_question: '你们公司在哪?', degraded: false },
  { id: 'inquiry', name_zh: '基本咨询', intent: 'product_inquiry', trap_question: '支持哪些支付?', degraded: false },
  { id: 'complaint', name_zh: '通用投诉', intent: 'complaint', trap_question: '投诉热线是多少?', degraded: false },
  { id: 'purchase', name_zh: '购买意向', intent: 'purchase_intent', trap_question: '有教育优惠吗?', degraded: false },
  { id: 'lang-barrier', name_zh: '语言障碍', intent: 'language_barrier', trap_question: 'Can you speak English?', degraded: true },
] as const;

function mockGenerate(): Promise<SimDialogUI[]> {
  return new Promise(resolve => setTimeout(() => {
    resolve(Array.from({ length: 12 }, (_, i) => {
      const persona = PERSONAS[i % PERSONAS.length];
      const scenario = SCENARIOS[i % SCENARIOS.length];
      const turns: SimTurnUI[] = [
        { role: 'customer', content: '你好，我想咨询', metadata: {} },
        { role: 'agent', content: '您好！请问有什么可以帮到您？', metadata: {} },
        { role: 'customer', content: scenario.trap_question, metadata: i < 2 ? { is_trap: true } : {} },
        { role: 'agent', content: '好的，我来帮您确认一下。', metadata: {} },
      ];
      return {
        id: `dialog-${String(i + 1).padStart(3, '0')}`,
        scenario: { ...scenario, keywords: [] },
        persona: { ...persona, traits: [...persona.traits] },
        turns, language: 'zh', review_status: 'pending' as const,
      };
    }));
  }, 1500));
}

interface Props { tenantId: string; }

export function VirtualRehearsalStep({ tenantId }: Props) {
  const { rehearsalDialogs, rehearsalLoading, setRehearsalDialogs, setRehearsalLoading, updateDialogReviewStatus } = useAdminStore();
  const reviewed = rehearsalDialogs.filter(d => d.review_status !== 'pending').length;
  const total = rehearsalDialogs.length;

  useEffect(() => { void tenantId; }, [tenantId]);

  const handleStart = async () => {
    setRehearsalLoading(true);
    try {
      const dialogs = await postJSON<SimDialogUI[]>(`/api/rehearsal/generate?tenant_id=${tenantId}`);
      setRehearsalDialogs(dialogs);
    } catch {
      // Fallback to local mock if API fails
      const dialogs = await mockGenerate();
      setRehearsalDialogs(dialogs);
    } finally {
      setRehearsalLoading(false);
    }
  };

  return (
    <div data-testid="virtual-rehearsal-step">
      <div className="cs-card hl">
        <div className="cs-ct"><span className="num">3</span>虚拟客户预演</div>

        {rehearsalDialogs.length === 0 && !rehearsalLoading && (
          <button className="cs-btn ok" data-testid="btn-start-rehearsal" onClick={handleStart}>开始预演</button>
        )}
        {rehearsalLoading && <div className="im-empty" data-testid="rehearsal-loading">正在生成虚拟对话...</div>}
      </div>

      {total > 0 && !rehearsalLoading && (
        <>
          <div className="cs-pg" data-testid="rehearsal-progress" style={{ marginTop: 10 }}>
            ~30 min · 已审 {reviewed} / {total} 条
          </div>

          <div data-testid="dialog-list" style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
            {rehearsalDialogs.map(dialog => (
              <div key={dialog.id} data-testid={`dialog-card-${dialog.id}`} className="cs-mock">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>
                    {dialog.scenario.name_zh} · {dialog.persona.name_zh}
                    {dialog.scenario.degraded && <span style={{ color: 'var(--l700)', marginLeft: 6, fontSize: 10 }} data-testid={`degraded-tag-${dialog.id}`}>降级</span>}
                  </span>
                  <span style={{ fontSize: 10, color: dialog.review_status === 'approved' ? 'var(--m600)' : dialog.review_status === 'flagged' ? 'var(--l700)' : 'var(--silver)', fontWeight: 700 }}>
                    {dialog.review_status === 'approved' ? '✓ 通过' : dialog.review_status === 'flagged' ? '⚠ 标记' : '待审'}
                  </span>
                </div>

                <div data-testid={`dialog-turns-${dialog.id}`}>
                  {dialog.turns.map((turn, idx) => (
                    <div key={idx} style={{ marginBottom: 6 }}>
                      <div className="lb">{turn.role === 'customer' ? '虚拟客户' : 'AI 回答'}</div>
                      <div className={turn.role === 'agent' ? 'ai' : ''}>
                        {turn.content}
                        {turn.metadata?.is_trap && <span style={{ color: 'var(--p)', fontSize: 10, marginLeft: 6 }} data-testid={`trap-tag-${dialog.id}`}>陷阱题</span>}
                      </div>
                    </div>
                  ))}
                </div>

                {dialog.review_status === 'pending' && (
                  <div className="cs-btns" style={{ marginTop: 8 }}>
                    <button className="cs-btn ok" data-testid={`btn-approve-${dialog.id}`} onClick={() => updateDialogReviewStatus(dialog.id, 'approved')}>✓ 通过</button>
                    <button className="cs-btn" data-testid={`btn-flag-${dialog.id}`} onClick={() => updateDialogReviewStatus(dialog.id, 'flagged')} style={{ background: 'var(--l500)', color: 'var(--l800)', border: 'none' }}>✎ 修改</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
