import { useEffect, useRef, useCallback, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { IMTitlebar } from './IMTitlebar';
import { IMSidebar } from './IMSidebar';
import { ConversationFeed } from './ConversationFeed';
import { CopilotView } from './CopilotView';
import { IMInput } from './IMInput';

const WS_URL = `ws://${window.location.hostname}:8000/ws/operator`;

type Pane = 'queue' | 'chat' | 'crm';

function getInitialPane(): Pane {
  try {
    const p = localStorage.getItem('as-op-pane');
    if (p === 'queue' || p === 'chat' || p === 'crm') return p;
  } catch { /* noop */ }
  return 'queue';
}

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
  const { t } = useTranslation();
  return (
    <div className="op-chat-empty" data-testid="chat-empty">
      <svg viewBox="0 0 240 160" width="180" height="120" aria-hidden="true">
        <path d="M30,90 Q120,70 210,95" stroke="var(--mountain-400)" strokeWidth="1" fill="none" opacity="0.6" />
        <path d="M50,110 Q120,95 200,115" stroke="var(--mountain-200)" strokeWidth="1" fill="none" opacity="0.5" />
        <ellipse cx="80" cy="92" rx="14" ry="3" fill="var(--ink-700)" opacity="0.7" />
        <line x1="80" y1="92" x2="80" y2="78" stroke="var(--ink-700)" strokeWidth="1" opacity="0.7" />
        <ellipse cx="140" cy="98" rx="10" ry="2.5" fill="var(--ink-700)" opacity="0.6" />
        <line x1="140" y1="98" x2="140" y2="86" stroke="var(--ink-700)" strokeWidth="1" opacity="0.6" />
        <ellipse cx="180" cy="105" rx="8" ry="2" fill="var(--ink-700)" opacity="0.4" />
        <line x1="180" y1="105" x2="180" y2="95" stroke="var(--ink-700)" strokeWidth="1" opacity="0.4" />
      </svg>
      <h3>{t('operator.empty.title')}</h3>
      <p>{t('operator.empty.desc')}</p>
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

/* ── Bottom mobile tab bar (队列 / 聊天 / 详情) ── */
function MobileTabbar({
  pane, setPane, hasActive, waitCount,
}: {
  pane: Pane;
  setPane: (p: Pane) => void;
  hasActive: boolean;
  waitCount: number;
}) {
  const { t } = useTranslation();
  return (
    <nav className="op-mobile-tabbar" aria-label={t('operator.mobile.tabbar.aria')} data-testid="op-mobile-tabbar">
      <button
        type="button"
        className={pane === 'queue' ? 'active' : ''}
        onClick={() => setPane('queue')}
        aria-label={t('operator.mobile.tab.queue')}
        data-testid="tab-queue"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="5" rx="1.5" />
          <rect x="3" y="11" width="18" height="5" rx="1.5" />
          <rect x="3" y="18" width="18" height="2.5" rx="1" />
        </svg>
        <span className="op-tab-lbl">{t('operator.mobile.tab.queue')}</span>
        {waitCount > 0 && <span className="op-tab-badge" data-testid="tab-queue-badge">{waitCount}</span>}
      </button>
      <button
        type="button"
        className={pane === 'chat' ? 'active' : ''}
        onClick={() => setPane('chat')}
        disabled={!hasActive}
        aria-label={t('operator.mobile.tab.chat')}
        data-testid="tab-chat"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" />
        </svg>
        <span className="op-tab-lbl">{t('operator.mobile.tab.chat')}</span>
      </button>
      <button
        type="button"
        className={pane === 'crm' ? 'active' : ''}
        onClick={() => setPane('crm')}
        disabled={!hasActive}
        aria-label={t('operator.mobile.tab.crm')}
        data-testid="tab-crm"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21v-1a7 7 0 0 1 14 0v1" />
        </svg>
        <span className="op-tab-lbl">{t('operator.mobile.tab.crm')}</span>
      </button>
    </nav>
  );
}

export function WorkspacePage() {
  const { t } = useTranslation();
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const openCopilot = useOperatorStore((s) => s.openCopilot);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const operatorId = useOperatorStore((s) => s.operatorId);
  const conversations = useOperatorStore((s) => s.conversations);

  const [navOpen, setNavOpen] = useState(false);
  const [pane, setPane] = useState<Pane>(getInitialPane);

  const { send, fetchHistory } = useOperatorWS(WS_URL);

  useNotificationSound();

  // Count cards in escalation-pending state → shown as a badge on the queue tab
  const waitCount = Object.values(conversations).filter(
    (c) => (c as any).state === 'escalation-pending',
  ).length;

  // Persist pane + mirror to root data-pane attribute so CSS can target
  useEffect(() => {
    try { localStorage.setItem('as-op-pane', pane); } catch { /* noop */ }
    const el = document.querySelector('.im-w');
    if (el) el.setAttribute('data-pane', pane);
  }, [pane]);

  const isMobile = () => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(max-width: 900px)').matches;
  };

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
    // On mobile, auto-switch to the chat pane when a card is picked
    if (isMobile()) setPane('chat');
  };

  const closeNav = () => setNavOpen(false);
  const openNav = () => setNavOpen(true);

  const hasActive = Boolean(activeCopilotConvId);

  return (
    <div className="im-w" data-testid="workspace-page" data-pane={pane}>
      <IMTitlebar onToggleNav={openNav} />
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
      <div
        className={`op-side-backdrop ${navOpen ? 'on' : ''}`}
        data-testid="op-side-backdrop"
        onClick={closeNav}
      />
      <div className="im-body">
        <IMSidebar onLogout={logout} open={navOpen} onClose={closeNav} />
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
      <MobileTabbar
        pane={pane}
        setPane={setPane}
        hasActive={hasActive}
        waitCount={waitCount}
      />
    </div>
  );
}
