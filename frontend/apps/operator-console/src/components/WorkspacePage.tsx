import { useState } from 'react';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { IMTitlebar } from './IMTitlebar';
import { IMSidebar } from './IMSidebar';
import { ConversationFeed } from './ConversationFeed';
import { CopilotView } from './CopilotView';
import { IMInput } from './IMInput';

const WS_URL =
  typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL
    ? (import.meta as any).env.VITE_WS_URL
    : 'ws://localhost:9999/ws/operator';

export function WorkspacePage() {
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const squads = useOperatorStore((s) => s.squads);
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  const logout = useOperatorStore((s) => s.logout);
  const addSquad = useOperatorStore((s) => s.addSquad);
  const openCopilot = useOperatorStore((s) => s.openCopilot);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);

  const [newSquadId, setNewSquadId] = useState('');

  const { send } = useOperatorWS(WS_URL);

  const handleAddSquad = () => {
    if (!newSquadId.trim()) return;
    addSquad(newSquadId.trim());
    setNewSquadId('');
  };

  return (
    <div className="im-w" data-testid="workspace-page">
      <IMTitlebar />
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
          {wsStatus === 'connecting' ? '\u8FDE\u63A5\u4E2D...' : '\u8FDE\u63A5\u5DF2\u65AD\u5F00\uFF0C\u5C1D\u8BD5\u91CD\u8FDE'}
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
                  {activeSquadId ?? '\u5DE5\u4F5C\u53F0'}
                </div>
                <div className="im-main-subtitle">
                  {squads.length === 0
                    ? '\u8BF7\u6DFB\u52A0 Squad ID'
                    : `${Object.keys(useOperatorStore.getState().conversations).length} \u4E2A\u5BF9\u8BDD`}
                </div>
              </div>
              <ConversationFeed
                squadId={activeSquadId}
                onCardClick={openCopilot}
              />
              <div className="im-input">
                <div className="im-input-row">
                  <input
                    data-testid="input-squad-id"
                    value={newSquadId}
                    onChange={(e) => setNewSquadId(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddSquad()}
                    placeholder="Squad ID"
                    style={{
                      flex: 1,
                      border: '1px solid var(--oat)',
                      borderRadius: 13,
                      padding: '9px 14px',
                      fontSize: 12,
                      fontFamily: 'var(--font-sans)',
                      outline: 'none',
                    }}
                  />
                  <button
                    data-testid="btn-add-squad"
                    onClick={handleAddSquad}
                  >
                    +
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
