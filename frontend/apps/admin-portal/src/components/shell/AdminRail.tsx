import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

interface RailItem {
  key: TabKey;
  labelKey: string;
  group: 'ops' | 'config';
  icon: React.ReactNode;
}

const ChatIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />
  </svg>
);
const DashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="9" />
    <rect x="14" y="3" width="7" height="5" />
    <rect x="14" y="12" width="7" height="9" />
    <rect x="3" y="16" width="7" height="5" />
  </svg>
);
const WizardIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v18M5 12h14" />
  </svg>
);
const BulbIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.74V17h8v-2.26A7 7 0 0 0 12 2Z" />
  </svg>
);
const CardIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="5" width="20" height="14" rx="2" />
    <path d="M2 10h20" />
  </svg>
);
const ChevIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6" />
  </svg>
);

const ITEMS: RailItem[] = [
  { key: 'notifications', icon: <ChatIcon />, labelKey: 'admin.nav.management_chat', group: 'ops' },
  { key: 'dashboard',     icon: <DashIcon />, labelKey: 'admin.nav.dashboard',       group: 'ops' },
  { key: 'wizard',        icon: <WizardIcon />, labelKey: 'admin.nav.wizard',        group: 'ops' },
  { key: 'proposals',     icon: <BulbIcon />, labelKey: 'admin.nav.proposals',       group: 'ops' },
  { key: 'billing',       icon: <CardIcon />, labelKey: 'admin.nav.billing',         group: 'config' },
];

interface AdminRailProps {
  open?: boolean;
  onClose?: () => void;
}

export function AdminRail({ open = false, onClose }: AdminRailProps = {}) {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  const handlePick = (key: TabKey) => {
    setActiveTab(key);
    onClose?.();
  };

  const renderItem = (item: RailItem) => {
    const label = t(item.labelKey);
    const isActive = activeTab === item.key;
    return (
      <li
        key={item.key}
        data-testid={`tab-${item.key}`}
        className={`cs-nav-item ${isActive ? 'active' : ''}`}
        onClick={() => handlePick(item.key)}
        aria-current={isActive ? 'page' : undefined}
      >
        {item.icon}
        <span className="cs-nav-label">{label}</span>
      </li>
    );
  };

  const opsItems = ITEMS.filter((i) => i.group === 'ops');
  const configItems = ITEMS.filter((i) => i.group === 'config');
  const tenant = tenantId ?? 'mystore';

  return (
    <aside className={`cs-rail ${open ? 'open' : ''}`} data-testid="admin-rail" aria-label="Admin navigation">
      <div className="cs-brand">
        <div className="cs-brand-wm">{'OneSyn · autoservice'}</div>
        <div className="cs-brand-sub">{'admin / v1.1'}</div>
      </div>

      <div className="cs-workspace">
        <div className="cs-workspace-logo">{tenant.slice(0, 1).toUpperCase()}</div>
        <div className="cs-workspace-info">
          <div className="cs-workspace-nm">{tenant}</div>
          <div className="cs-workspace-plan">{'plan: growth · 2/3 seats'}</div>
        </div>
        <span className="cs-workspace-chev"><ChevIcon /></span>
      </div>

      <div className="cs-nav-sec">{t('admin.nav.section.ops')}</div>
      <ul className="cs-nav">{opsItems.map(renderItem)}</ul>

      <div className="cs-nav-sec">{t('admin.nav.section.config')}</div>
      <ul className="cs-nav">{configItems.map(renderItem)}</ul>

      <div className="cs-usage-card">
        <div className="cs-usage-ttl">
          <span>{t('admin.usage.title')}</span>
          <b>{'68%'}</b>
        </div>
        <div className="cs-usage-nm">{t('admin.usage.month')}</div>
        <div className="cs-usage-val">{t('admin.usage.progress', { used: '13,605', total: '20,000' })}</div>
        <div className="cs-usage-bar">
          <div className="cs-usage-fill" style={{ width: '68%' }} />
        </div>
        <div className="cs-usage-foot">
          <span>{t('admin.usage.period')}</span>
          <span>{t('admin.usage.remaining', { days: 10 })}</span>
        </div>
        <button type="button" className="cs-usage-upgrade">{t('admin.usage.upgrade_cta')}</button>
      </div>

      <div className="cs-rail-spacer" />
    </aside>
  );
}
