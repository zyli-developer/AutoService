import { useEffect, useRef, useCallback } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { IMTitlebar } from './IMTitlebar';
import { IMSidebar } from './IMSidebar';
import { ConversationFeed } from './ConversationFeed';
import { CopilotView } from './CopilotView';
import { IMInput } from './IMInput';

const WS_URL = `ws://${window.location.hostname}:8000/ws/operator`;

/* ── ConcurrencyWarning ── */
function ConcurrencyWarning() {
  const { t } = useTranslation();
  const count = useOperatorStore(
    (s) => Object.keys(s.conversations).length,
  );
  const limit = useOperatorStore((s) => s.concurrencyLimit);
  if (count < limit - 1) return null;
  const atLimit = count >= limit;
  return (
    <div
      data-testid="concurrency-warning"
      className={`op-notif ${atLimit ? 'danger' : 'warn'}`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0ZM12 9v4M12 17h.01" />
      </svg>
      <span>
        {atLimit
          ? t('operator.concurrency.at_limit', { limit })
          : t('operator.concurrency.approaching', { count, limit })}
      </span>
    </div>
  );
}

function ChatEmpty() {
  return (
    <div className="op-chat-empty" data-testid="chat-empty">
      <svg viewBox="0 0 240 160" width="180" height="120" aria-hidden="true">
        <defs>
          <linearGradient id="ink-grad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="var(--ink-50)" />
            <stop offset="100%" stopColor="var(--mountain-200)" />
          </linearGradient>
        </defs>
        {/* distant boats — abstract sumi-e style */}
        <path d="M30,90 Q120,70 210,95" stroke="var(--mountain-400)" strokeWidth="1" fill="none" opacity="0.6" />
        <path d="M50,110 Q120,95 200,115" stroke="var(--mountain-200)" strokeWidth="1" fill="none" opacity="0.5" />
        <ellipse cx="80" cy="92" rx="14" ry="3" fill="var(--ink-700)" opacity="0.7" />
        <line x1="80" y1="92" x2="80" y2="78" stroke="var(--ink-700)" strokeWidth="1" opacity="0.7" />
        <ellipse cx="140" cy="98" rx="10" ry="2.5" fill="var(--ink-700)" opacity="0.6" />
        <line x1="140" y1="98" x2="140" y2="86" stroke="var(--ink-700)" strokeWidth="1" opacity="0.6" />
        <ellipse cx="180" cy="105" rx="8" ry="2" fill="var(--ink-700)" opacity="0.4" />
        <line x1="180" y1="105" x2="180" y2="95" stroke="var(--ink-700)" strokeWidth="1" opacity="0.4" />
      </svg>
      <h3>点开任意卡片进入 Copilot</h3>
      <p>
        你不需要先开口。打开卡片，zchat 自动进入 copilot 模式，
        客户端无感知，你可以从容观察 Agent 的回复、在侧栏输入建议。
      </p>
    </div>
  );
}

/* ── useNotificationSound ── */
function useNotificationSound() {
  const prevCountRef = useRef(0);
  const conversations = useOperatorStore((s) => s.conversations);
  const count = Object.keys(conversations).length;

  const playSound = useCallback(() => {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.15;
      osc.connect(gain).connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.15);
    } catch {
      // AudioContext may not be available
    }
  }, []);

  useEffect(() => {
    if (count > prevCountRef.current) {
      playSound();
    }
    prevCountRef.current = count;
  }, [count, playSound]);
}

export function WorkspacePage() {
  const { t } = useTranslation();
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const openCopilot = useOperatorStore((s) => s.openCopilot);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const operatorId = useOperatorStore((s) => s.operatorId);

  const { send, fetchHistory } = useOperatorWS(WS_URL);

  useNotificationSound();

  const handleOpenCopilot = (convId: string) => {
    openCopilot(convId);
    fetchHistory(convId);
    send({
      v: 1,
      type: 'operator_join' as any,
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: convId, operator_id: operatorId || 'operator' },
    } as any);
  };

  return (
    <div className="im-w" data-testid="workspace-page">
      <IMTitlebar />
      <ConcurrencyWarning />
      {wsStatus !== 'open' && wsStatus !== 'idle' && (
        <div
          data-testid="connection-banner"
          className={`op-notif ${wsStatus === 'connecting' ? 'warn' : 'danger'}`}
        >
          <span>
            {wsStatus === 'connecting' ? t('connection.connecting') : t('connection.disconnected')}
          </span>
        </div>
      )}
      <div className="im-body">
        <IMSidebar onLogout={logout} />
        <main className={`im-main ${activeCopilotConvId ? 'with-chat' : ''}`}>
          <section className="op-cards-col">
            <ConversationFeed
              squadId={activeSquadId}
              onCardClick={handleOpenCopilot}
            />
          </section>
          {activeCopilotConvId ? (
            <>
              <CopilotView send={send} />
              <IMInput send={send} />
            </>
          ) : (
            <ChatEmpty />
          )}
        </main>
      </div>
    </div>
  );
}
