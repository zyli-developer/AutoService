import { useAdminStore } from '../../store/adminStore';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

interface RailItem {
  key: TabKey;
  icon: string;
  label: string;
}

const ITEMS: RailItem[] = [
  { key: 'notifications', icon: '🗨', label: '管理群' },
  { key: 'dashboard', icon: '📊', label: '仪表盘' },
  { key: 'wizard', icon: '✨', label: '向导' },
  { key: 'proposals', icon: '💡', label: '提案' },
  { key: 'billing', icon: '💳', label: '账单' },
];

export function AdminRail() {
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  return (
    <nav className="cs-rail" data-testid="admin-rail" aria-label="Admin navigation">
      {ITEMS.map((item) => (
        <button
          key={item.key}
          type="button"
          data-testid={`tab-${item.key}`}
          className={`cs-rail-item ${activeTab === item.key ? 'active' : ''}`}
          onClick={() => setActiveTab(item.key)}
          aria-label={item.label}
          aria-current={activeTab === item.key ? 'page' : undefined}
        >
          <span aria-hidden="true">{item.icon}</span>
          <span className="cs-rail-tooltip">{item.label}</span>
        </button>
      ))}
      <div className="cs-rail-spacer" />
    </nav>
  );
}
