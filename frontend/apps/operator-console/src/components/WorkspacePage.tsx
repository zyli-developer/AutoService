import { useState } from 'react';
import { useOperatorStore } from '../store/operatorStore';
import { useOperatorWS } from '../hooks/useOperatorWS';
import { IMTitlebar } from './IMTitlebar';
import { IMSidebar } from './IMSidebar';
import { ConversationFeed } from './ConversationFeed';
import { CopilotView } from './CopilotView';
import { IMInput } from './IMInput';

const WS_URL = `ws://${window.location.hostname}:8000/ws/operator`;

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
                  {activeSquadId ?? '工作台'}
                </div>
                <div className="im-main-subtitle">
                  {squads.length === 0
                    ? '请添加 Squad ID'
                    : `${Object.keys(useOperatorStore.getState().conversations).length} 个对话`}
                </div>
              </div>
              <ConversationFeed
                squadId={null}
                onCardClick={openCopilot}
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
