import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

interface RailItem {
  key: TabKey;
  icon: string;
  labelKey: string;
}

const ITEMS: RailItem[] = [
  { key: 'notifications', icon: '🗨', labelKey: 'admin.nav.management_chat' },
  { key: 'dashboard', icon: '📊', labelKey: 'admin.nav.dashboard' },
  { key: 'wizard', icon: '✨', labelKey: 'admin.nav.wizard' },
  { key: 'proposals', icon: '💡', labelKey: 'admin.nav.proposals' },
  { key: 'billing', icon: '💳', labelKey: 'admin.nav.billing' },
];

export function AdminRail() {
  const { t } = useTranslation();
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  return (
    <nav className="cs-rail" data-testid="admin-rail" aria-label="Admin navigation">
      {ITEMS.map((item) => {
        const label = t(item.labelKey);
        return (
          <button
            key={item.key}
            type="button"
            data-testid={`tab-${item.key}`}
            className={`cs-rail-item ${activeTab === item.key ? 'active' : ''}`}
            onClick={() => setActiveTab(item.key)}
            aria-label={label}
            aria-current={activeTab === item.key ? 'page' : undefined}
          >
            <span aria-hidden="true">{item.icon}</span>
            <span className="cs-rail-tooltip">{label}</span>
          </button>
        );
      })}
      <div className="cs-rail-spacer" />
    </nav>
  );
}
