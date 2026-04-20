import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

interface IMSidebarProps {
  onLogout: () => void;
}

const InboxIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z" />
  </svg>
);

const SquadIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

const BookIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
  </svg>
);

const BellIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);

export function IMSidebar({ onLogout }: IMSidebarProps) {
  const { t } = useTranslation();
  const operatorId = useOperatorStore((s) => s.operatorId);
  const squads = useOperatorStore((s) => s.squads);
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const setActiveSquad = useOperatorStore((s) => s.setActiveSquad);
  const unreadCounts = useOperatorStore((s) => s.unreadCounts);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const conversations = useOperatorStore((s) => s.conversations);
  const concurrencyLimit = useOperatorStore((s) => s.concurrencyLimit);

  const totalConvs = Object.keys(conversations).length;
  const operatorDisplay = operatorId ?? t('operator.sidebar.default_operator');

  return (
    <aside className="im-sidebar" data-testid="im-sidebar">
      <div className="im-brand">
        <div className="im-brand-wm">{'OneSyn · autoservice'}</div>
        <div className="im-brand-sub">{'operator / v1.1'}</div>
      </div>

      <div className="im-me">
        <div className="im-me-av">{operatorDisplay.slice(0, 1).toUpperCase()}</div>
        <div className="im-me-info">
          <div className="im-me-nm" data-testid="operator-name">{operatorDisplay}</div>
          <div className="im-me-rl">
            {t('operator.sidebar.online_concurrency', { count: totalConvs, limit: concurrencyLimit })}
          </div>
        </div>
      </div>

      <div className="im-nav-sec">{t('operator.sidebar.channels')}</div>
      <ul className="im-nav">
        <li
          className={`im-nav-item ${!activeSquadId ? 'active' : ''}`}
          data-testid="channel-all"
          onClick={() => setActiveSquad(null as any)}
        >
          <InboxIcon />
          <span>{t('operator.sidebar.all_conversations')}</span>
          {totalConvs > 0 && <span className="im-nav-count">{totalConvs}</span>}
        </li>
        {squads.map((squadId) => {
          const unread = unreadCounts[squadId] ?? 0;
          return (
            <li
              key={squadId}
              className={`im-nav-item ${activeSquadId === squadId ? 'active' : ''}`}
              data-testid={`channel-${squadId}`}
              onClick={() => setActiveSquad(squadId)}
            >
              <SquadIcon />
              <span>{squadId}</span>
              {unread > 0 && (
                <span className="im-nav-count urgent" data-testid={`unread-badge-${squadId}`}>
                  {unread}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {activeCopilotConvId && (
        <>
          <div className="im-nav-sec">{t('operator.sidebar.direct_messages')}</div>
          <ul className="im-nav">
            <li className="im-nav-item dm active" data-testid="dm-copilot">
              <span className="im-dm-dot" />
              <span>
                {t('operator.sidebar.conversation_prefix')} {activeCopilotConvId.slice(0, 6)}
              </span>
            </li>
          </ul>
        </>
      )}

      <div className="im-nav-sec">{t('operator.sidebar.resources')}</div>
      <ul className="im-nav">
        <li className="im-nav-item">
          <BookIcon />
          <span>{t('operator.sidebar.knowledge_base')}</span>
        </li>
        <li className="im-nav-item">
          <BellIcon />
          <span>{t('operator.sidebar.notifications_center')}</span>
        </li>
      </ul>

      <div className="im-side-foot">
        <div className="im-side-foot-row"><span>{t('operator.sidebar.today_takeovers')}</span><b>—</b></div>
        <div className="im-side-foot-row"><span>{t('operator.sidebar.csat')}</span><b>—</b></div>
        <div className="im-side-foot-row"><span>{t('operator.sidebar.p95')}</span><b>—</b></div>
        <div className="im-side-foot-row">
          <span className="im-zchat-label">zchat</span>
          <span className="im-zchat-status">● connected</span>
        </div>
        <button
          type="button"
          data-testid="btn-logout"
          onClick={onLogout}
          className="im-side-logout"
        >
          {t('common.logout')}
        </button>
      </div>
    </aside>
  );
}
