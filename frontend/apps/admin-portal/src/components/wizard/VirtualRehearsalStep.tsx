import { useEffect } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';
import type { SimDialogUI, SimTurnUI } from '../../store/adminStore';
import { postJSON } from '../../api';

type ReviewStatus = 'approved' | 'flagged';

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
  const { t } = useTranslation();
  const { rehearsalDialogs, rehearsalLoading, setRehearsalDialogs, setRehearsalLoading, updateDialogReviewStatus } = useAdminStore();
  const reviewed = rehearsalDialogs.filter(d => d.review_status !== 'pending').length;
  const total = rehearsalDialogs.length;

  useEffect(() => { void tenantId; }, [tenantId]);

  const handleStart = async () => {
    setRehearsalLoading(true);
    try {
      const resp = await postJSON<{ demo_mode: boolean; dialogs: SimDialogUI[] }>(`/api/rehearsal/generate?tenant_id=${tenantId}`);
      setRehearsalDialogs(Array.isArray(resp?.dialogs) ? resp.dialogs : []);
    } catch {
      // Fallback to local mock if API fails
      const dialogs = await mockGenerate();
      setRehearsalDialogs(dialogs);
    } finally {
      setRehearsalLoading(false);
    }
  };

  // T1F.7: persist review status via /api/rehearsal/review (T1B.3 endpoint).
  // We optimistically update local state for instant feedback; on API failure
  // the local state already reflects the attempt (matches the pre-T1F.7 UX).
  const handleReview = async (dialogId: string, status: ReviewStatus) => {
    updateDialogReviewStatus(dialogId, status);
    try {
      await postJSON<{ status: string; dialog_id: string; review_status: string }>(
        '/api/rehearsal/review',
        {
          tenant_id: tenantId,
          dialog_id: dialogId,
          review_status: status,
        },
      );
    } catch {
      // Swallow — local state already reflects the user's intent; backend
      // persistence is best-effort for M1 (demo-mode dialogs aren't in
      // rehearsal.json and /review returns 404 for them, which is expected).
    }
  };

  return (
    <div data-testid="virtual-rehearsal-step">
      <div className="cs-card hl">
        <div className="cs-ct"><span className="num">3</span>{t('admin.wizard.rehearsal.title')}</div>

        {rehearsalDialogs.length === 0 && !rehearsalLoading && (
          <button className="cs-btn ok" data-testid="btn-start-rehearsal" onClick={handleStart}>{t('admin.wizard.rehearsal.start')}</button>
        )}
        {rehearsalLoading && <div className="im-empty" data-testid="rehearsal-loading">{t('admin.wizard.rehearsal.generating')}</div>}
      </div>

      {total > 0 && !rehearsalLoading && (
        <>
          <div className="cs-pg" data-testid="rehearsal-progress" style={{ marginTop: 10 }}>
            {t('admin.wizard.rehearsal.approved_count', { passed: reviewed, total })}
          </div>

          <div data-testid="dialog-list" style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14 }}>
            {rehearsalDialogs.map(dialog => (
              <div key={dialog.id} data-testid={`dialog-card-${dialog.id}`} className="cs-mock">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>
                    {dialog.scenario.name_zh} · {dialog.persona.name_zh}
                    {dialog.scenario.degraded && <span style={{ color: 'var(--l700)', marginLeft: 6, fontSize: 10 }} data-testid={`degraded-tag-${dialog.id}`}>{t('admin.wizard.rehearsal.degraded')}</span>}
                  </span>
                  <span style={{ fontSize: 10, color: dialog.review_status === 'approved' ? 'var(--m600)' : dialog.review_status === 'flagged' ? 'var(--l700)' : 'var(--silver)', fontWeight: 700 }}>
                    {dialog.review_status === 'approved'
                      ? t('admin.wizard.rehearsal.pass')
                      : dialog.review_status === 'flagged'
                        ? t('admin.wizard.rehearsal.flagged')
                        : t('admin.wizard.rehearsal.pending')}
                  </span>
                </div>

                <div data-testid={`dialog-turns-${dialog.id}`}>
                  {dialog.turns.map((turn, idx) => (
                    <div key={idx} style={{ marginBottom: 6 }}>
                      <div className="lb">{turn.role === 'customer' ? t('admin.wizard.rehearsal.virtual_customer') : t('admin.wizard.rehearsal.ai_reply')}</div>
                      <div className={turn.role === 'agent' ? 'ai' : ''}>
                        {turn.content}
                        {!!turn.metadata?.is_trap && <span style={{ color: 'var(--p)', fontSize: 10, marginLeft: 6 }} data-testid={`trap-tag-${dialog.id}`}>{t('admin.wizard.rehearsal.trap')}</span>}
                      </div>
                    </div>
                  ))}
                </div>

                {dialog.review_status === 'pending' && (
                  <div className="cs-btns" style={{ marginTop: 8 }}>
                    <button className="cs-btn ok" data-testid={`btn-approve-${dialog.id}`} onClick={() => handleReview(dialog.id, 'approved')}>{t('admin.wizard.rehearsal.pass')}</button>
                    <button className="cs-btn" data-testid={`btn-flag-${dialog.id}`} onClick={() => handleReview(dialog.id, 'flagged')} style={{ background: 'var(--l500)', color: 'var(--l800)', border: 'none' }}>{t('admin.wizard.rehearsal.edit')}</button>
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
