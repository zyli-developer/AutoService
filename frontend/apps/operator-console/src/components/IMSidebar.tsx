import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

interface IMSidebarProps {
  onLogout: () => void;
}

export function IMSidebar({ onLogout }: IMSidebarProps) {
  const { t } = useTranslation();
  const operatorId = useOperatorStore((s) => s.operatorId);
  const squads = useOperatorStore((s) => s.squads);
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const setActiveSquad = useOperatorStore((s) => s.setActiveSquad);
  const unreadCounts = useOperatorStore((s) => s.unreadCounts);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);

  return (
    <div className="im-sidebar" data-testid="im-sidebar">
      <div className="im-ws-header">
        <div className="im-ws-title">{t('operator.sidebar.workspace')}</div>
        <div className="im-ws-user" data-testid="operator-name">
          {operatorId ?? t('operator.sidebar.default_operator')}
        </div>
      </div>

      <div className="im-section-title">{t('operator.sidebar.channels')}</div>
      <div
        className={`im-channel ${!activeSquadId ? 'active' : ''}`}
        data-testid="channel-all"
        onClick={() => setActiveSquad(null as any)}
      >
        {t('operator.sidebar.all_conversations')}
      </div>
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

      <div className="im-section-title">{t('operator.sidebar.direct_messages')}</div>
      {activeCopilotConvId && (
        <div className="im-channel dm active" data-testid="dm-copilot">
          {t('operator.sidebar.conversation_prefix')} {activeCopilotConvId.slice(0, 6)}
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
          {t('common.logout')}
        </button>
      </div>
    </div>
  );
}
