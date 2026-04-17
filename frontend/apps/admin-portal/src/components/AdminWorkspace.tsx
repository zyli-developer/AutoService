import { useAdminStore } from '../store/adminStore';
import { WizardTab } from './WizardTab';
import { DashboardTab } from './DashboardTab';
import { ManagementChat } from './ManagementChat';
import { ProposalsTab } from './ProposalsTab';
import { BillingTab } from './BillingTab';

type TabKey = 'wizard' | 'dashboard' | 'notifications' | 'proposals' | 'billing';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'wizard', label: '向导' },
  { key: 'dashboard', label: '仪表盘' },
  { key: 'notifications', label: '管理群' },
  { key: 'proposals', label: '提案' },
  { key: 'billing', label: '账单' },
];

const TAB_CONTENT: Record<TabKey, React.ReactNode> = {
  wizard: <WizardTab />,
  dashboard: <DashboardTab />,
  notifications: <ManagementChat />,
  proposals: <ProposalsTab />,
  billing: <BillingTab />,
};

export function AdminWorkspace() {
  const tenantId = useAdminStore((s) => s.tenantId);
  const activeTab = useAdminStore((s) => s.activeTab) as TabKey;
  const setActiveTab = useAdminStore((s) => s.setActiveTab);
  const logout = useAdminStore((s) => s.logout);

  return (
    <div className="cs-w" data-testid="admin-workspace">
      <div className="cs-tb">
        <div className="cs-tb-dots"><span /><span /><span /></div>
        <div className="cs-app">console.onesync.io / {tenantId}</div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, color: 'var(--silver)' }} data-testid="tenant-id">{tenantId}</span>
          <button
            data-testid="btn-logout"
            onClick={logout}
            style={{ background: 'transparent', border: 'none', color: 'var(--silver)', fontSize: 11, cursor: 'pointer' }}
          >
            退出
          </button>
        </div>
      </div>
      <div className="cs-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`cs-tab ${activeTab === t.key ? 'active' : ''}`}
            data-testid={`tab-${t.key}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="cs-main">
        {TAB_CONTENT[activeTab]}
      </div>
    </div>
  );
}
