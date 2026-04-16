import { useAdminStore } from '../store/adminStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { WizardTab } from './WizardTab';
import { DashboardTab } from './DashboardTab';
import { NotificationsTab } from './NotificationsTab';
import { ProposalsTab } from './ProposalsTab';

const WS_URL =
  typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL
    ? (import.meta as any).env.VITE_WS_URL
    : 'ws://localhost:9999/ws/admin';

type TabKey = 'wizard' | 'dashboard' | 'notifications' | 'proposals';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'wizard', label: '\u5411\u5BFC' },
  { key: 'dashboard', label: '\u4EEA\u8868\u76D8' },
  { key: 'notifications', label: '\u901A\u77E5' },
  { key: 'proposals', label: '\u63D0\u6848' },
];

export function AdminWorkspace() {
  const tenantId = useAdminStore((s) => s.tenantId);
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);
  const logout = useAdminStore((s) => s.logout);
  const { status } = useWebSocket(WS_URL, 'admin-portal');

  const renderTab = () => {
    switch (activeTab) {
      case 'wizard': return <WizardTab />;
      case 'dashboard': return <DashboardTab />;
      case 'notifications': return <NotificationsTab />;
      case 'proposals': return <ProposalsTab />;
    }
  };

  return (
    <div className="cs-w" data-testid="admin-workspace">
      <div className="cs-tb">
        <div className="cs-tb-dots"><span /><span /><span /></div>
        <div className="cs-app">console.onesync.io / {tenantId}</div>
        <span
          data-testid="tenant-id"
          style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--silver)' }}
        >
          {tenantId}
        </span>
        <span style={{ fontSize: 10, color: status === 'open' ? 'var(--m600)' : 'var(--silver)', fontWeight: 700, marginLeft: 8 }}>
          WS: {status}
        </span>
        <button
          data-testid="btn-logout"
          onClick={logout}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--silver)',
            fontSize: 12,
            cursor: 'pointer',
            marginLeft: 8,
            fontFamily: 'var(--font-sans)',
          }}
        >
          {'\u9000\u51FA'}
        </button>
      </div>
      <div className="cs-main">
        <div className="cs-tabs" data-testid="admin-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              role="tab"
              className={`cs-tab ${activeTab === tab.key ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.key)}
              aria-selected={activeTab === tab.key}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {renderTab()}
      </div>
    </div>
  );
}
