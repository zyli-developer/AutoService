import { useOperatorStore } from '../store/operatorStore';

interface IMSidebarProps {
  onLogout: () => void;
}

export function IMSidebar({ onLogout }: IMSidebarProps) {
  const operatorId = useOperatorStore((s) => s.operatorId);
  const squads = useOperatorStore((s) => s.squads);
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const setActiveSquad = useOperatorStore((s) => s.setActiveSquad);
  const unreadCounts = useOperatorStore((s) => s.unreadCounts);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);

  return (
    <div className="im-sidebar" data-testid="im-sidebar">
      <div className="im-ws-header">
        <div className="im-ws-title">{'\u5546\u6237\u5DE5\u4F5C\u533A'}</div>
        <div className="im-ws-user" data-testid="operator-name">
          {operatorId ?? '\u5BA2\u670D'}
        </div>
      </div>

      <div className="im-section-title">{'\u9891\u9053'}</div>
      {squads.map((squadId) => {
        const unread = unreadCounts[squadId] ?? 0;
        return (
          <div
            key={squadId}
            className={`im-channel ${activeSquadId === squadId ? 'active' : ''}`}
            data-testid={`channel-${squadId}`}
            onClick={() => setActiveSquad(squadId)}
          >
            {squadId}
            {unread > 0 && (
              <span className="im-channel-badge" data-testid={`unread-badge-${squadId}`}>
                {unread}
              </span>
            )}
          </div>
        );
      })}

      <div className="im-section-title">{'\u76F4\u63A5\u6D88\u606F'}</div>
      {activeCopilotConvId && (
        <div className="im-channel dm active" data-testid="dm-copilot">
          {'\u5BF9\u8BDD'} {activeCopilotConvId.slice(0, 6)}
        </div>
      )}

      <div style={{ marginTop: 'auto', padding: '12px 16px' }}>
        <button
          data-testid="btn-logout"
          onClick={onLogout}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--silver)',
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'var(--font-sans)',
          }}
        >
          {'\u9000\u51FA'}
        </button>
      </div>
    </div>
  );
}
