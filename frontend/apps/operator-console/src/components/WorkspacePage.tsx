import { useEffect, useRef, useCallback, useMemo, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useTenantId } from '@autoservice/shared';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { useCCPoolStatus } from '../hooks/useCCPoolStatus';
import { IMTitlebar } from './IMTitlebar';
import { IMSidebar } from './IMSidebar';
import { ConversationFeed } from './ConversationFeed';
import { CopilotView } from './CopilotView';
import { NoTenantFallback } from './NoTenantFallback';
import { PoolBusyWarning } from './PoolBusyWarning';

/**
 * Build the operator WS URL for a given tenant.
 * Exported so tests (and future shared utilities) can assert the template.
 * See docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2.
 */
export function buildOperatorWsUrl(tenantId: string, hostname = window.location.hostname): string {
  return `ws://${hostname}:8000/ws/operator?tenant=${encodeURIComponent(tenantId)}`;
}

function ChatEmpty() {
  const { t } = useTranslation();
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

const isMobile = () =>
  typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches;

export function WorkspacePage() {
  const { t } = useTranslation();
  const tenantId = useTenantId();
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const openCopilot = useOperatorStore((s) => s.openCopilot);
  const closeCopilot = useOperatorStore((s) => s.closeCopilot);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const operatorId = useOperatorStore((s) => s.operatorId);

  const [navOpen, setNavOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [view, setView] = useState<'list' | 'chat'>(
    activeCopilotConvId ? 'chat' : 'list',
  );
  const [panelOpen, setPanelOpen] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('as-op-panel');
      if (saved === 'on') return true;
      if (saved === 'off') return false;
    } catch {
      /* noop */
    }
    return typeof window !== 'undefined' && window.innerWidth >= 1280;
  });

  useEffect(() => {
    try {
      localStorage.setItem('as-op-panel', panelOpen ? 'on' : 'off');
    } catch {
      /* noop */
    }
  }, [panelOpen]);

  // If the store opens/closes a conv externally, keep the mobile view in sync.
  useEffect(() => {
    if (activeCopilotConvId && isMobile()) setView('chat');
    if (!activeCopilotConvId) setView('list');
  }, [activeCopilotConvId]);

  // Build the WS URL with tenant context. If no tenant is present we fall
  // back to an empty string and skip the connection — see NoTenantFallback.
  const wsUrl = useMemo(
    () => (tenantId ? buildOperatorWsUrl(tenantId) : ''),
    [tenantId],
  );

  const { send, fetchHistory } = useOperatorWS(wsUrl);

  // Polls /api/cc_pool/runtime every 3 s → drives <PoolBusyWarning>.
  // Mounted here so it runs exactly once (WorkspacePage is a singleton in
  // the app tree). Safe to run before the tenant guard below — the hook
  // returns void and fires no requests until useEffect commits.
  useCCPoolStatus();

  if (!tenantId) {
    return <NoTenantFallback />;
  }

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
    if (isMobile()) setView('chat');
  };

  const backToList = () => {
    setView('list');
    setSheetOpen(false);
    closeCopilot();
  };

  return (
    <div className="im-w" data-testid="workspace-page">
      <IMTitlebar onHamburger={() => setNavOpen(true)} />
      <PoolBusyWarning />
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
        <button
          type="button"
          className={`im-side-backdrop ${navOpen ? 'on' : ''}`}
          data-testid="im-side-backdrop"
          aria-label={t('operator.topbar.close_menu')}
          onClick={() => setNavOpen(false)}
          tabIndex={navOpen ? 0 : -1}
        />
        <IMSidebar onLogout={logout} open={navOpen} onPick={() => setNavOpen(false)} />
        <main
          className={`im-main ${activeCopilotConvId ? 'with-chat' : ''}`}
          data-view={view}
          data-sheet={sheetOpen ? 'on' : 'off'}
        >
          <section className="op-cards-col">
            <ConversationFeed
              squadId={activeSquadId}
              onCardClick={handleOpenCopilot}
            />
          </section>
          <div className="op-chat-wrap">
            {activeCopilotConvId ? (
              <CopilotView
                send={send}
                panelOpen={panelOpen}
                onTogglePanel={() => setPanelOpen((v) => !v)}
                onOpenSheet={() => setSheetOpen(true)}
                onCloseSheet={() => setSheetOpen(false)}
                onBackToList={backToList}
              />
            ) : (
              <ChatEmpty />
            )}
            {/* Sheet backdrop must live INSIDE .op-chat-wrap so it shares
                the stacking context that the wrap's `transform` creates.
                Otherwise the wrap stacks at z:auto in .im-main while the
                backdrop sits at z:55 in the outer context — pushing the
                whole chat-wrap (including the sheet) underneath the blur. */}
            <button
              type="button"
              className={`im-sheet-backdrop ${sheetOpen ? 'on' : ''}`}
              data-testid="im-sheet-backdrop"
              aria-label={t('operator.chat.close_detail')}
              onClick={() => setSheetOpen(false)}
              tabIndex={sheetOpen ? 0 : -1}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
