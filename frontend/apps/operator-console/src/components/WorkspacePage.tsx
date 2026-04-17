import { useState, useEffect, useRef, useCallback } from 'react';
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
  const count = useOperatorStore(
    (s) => Object.keys(s.conversations).length,
  );
  const limit = useOperatorStore((s) => s.concurrencyLimit);
  if (count < limit - 1) return null;
  const atLimit = count >= limit;
  return (
    <div
      data-testid="concurrency-warning"
      style={{
        background: atLimit ? 'var(--p)' : 'var(--l400)',
        color: atLimit ? '#fff' : 'var(--l800)',
        padding: '6px 16px',
        textAlign: 'center',
        fontSize: 13,
      }}
    >
      {atLimit
        ? `已达并发上限 (${limit})，无法接入新对话`
        : `接近并发上限 (${count}/${limit})`}
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
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const squads = useOperatorStore((s) => s.squads);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const addSquad = useOperatorStore((s) => s.addSquad);
  const openCopilot = useOperatorStore((s) => s.openCopilot);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);

  const [newSquadId, setNewSquadId] = useState('');

  const { send, fetchHistory } = useOperatorWS(WS_URL);

  useNotificationSound();

  const handleOpenCopilot = (convId: string) => {
    openCopilot(convId);
    fetchHistory(convId);
  };

  const handleAddSquad = () => {
    if (!newSquadId.trim()) return;
    addSquad(newSquadId.trim());
    setNewSquadId('');
  };

  return (
    <div className="im-w" data-testid="workspace-page">
      <IMTitlebar />
      <ConcurrencyWarning />
      {wsStatus !== 'open' && wsStatus !== 'idle' && (
        <div
          data-testid="connection-banner"
          className="im-system"
          style={{
            background: wsStatus === 'connecting' ? 'var(--l400)' : 'var(--p)',
            color: wsStatus === 'connecting' ? 'var(--l800)' : '#fff',
            padding: '6px 16px',
          }}
        >
          {wsStatus === 'connecting' ? '连接中...' : '连接已断开，尝试重连'}
        </div>
      )}
      <div className="im-body">
        <IMSidebar onLogout={logout} />
        <div className="im-main">
          {activeCopilotConvId ? (
            <>
              <CopilotView send={send} />
              <IMInput send={send} />
            </>
          ) : (
            <>
              <div className="im-main-header">
                <div className="im-main-title">
                  {activeSquadId ? `# ${activeSquadId}` : '# 全部对话'}
                </div>
                <div className="im-main-subtitle">
                  {`${Object.values(useOperatorStore.getState().conversations).filter(c => !activeSquadId || c.squadId === activeSquadId).length} 个对话`}
                </div>
              </div>
              <ConversationFeed
                squadId={activeSquadId}
                onCardClick={handleOpenCopilot}
              />
              <div className="im-input">
                <div className="im-input-box">
                  等待客户接入...
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
