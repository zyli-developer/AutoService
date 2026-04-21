import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

/**
 * Rail variants (M2 spec §4.2).
 *
 * - `master` (default) — platform-admin rail; management-chat + cross-tenant
 *   nav + wizard-derived ops/config sections. Back-compat for all M1 callers
 *   that don't pass `variant`.
 * - `tenant` — fork-side 4-tab rail: Chat (→ `_local_admin`), Dashboard,
 *   Proposals, Billing. Master section (cross-tenant nav) is always hidden
 *   in this variant per spec §4.2 row 6 ("去除").
 */
export type RailVariant = 'master' | 'tenant';

type MasterTabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'dream' | 'billing';
type TenantTabKey = 'chat' | 'dashboard' | 'proposals' | 'dream' | 'billing';
type TabKey = MasterTabKey | TenantTabKey;

interface RailItem {
  key: TabKey;
  labelKey: string;
  group: 'ops' | 'config';
  icon: React.ReactNode;
  to: string;
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
const TenantsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 21V7l6-4 6 4v14" />
    <path d="M15 21V11l6 4v6" />
    <path d="M9 9v0M9 13v0M9 17v0" />
  </svg>
);
const DreamIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    <circle cx="17" cy="7" r="1" />
    <circle cx="19.5" cy="10" r="0.6" />
  </svg>
);

// Declarative variant → items map (spec §4.2 + key invariant from eval-doc-012).
// Branching lives in this table, NOT in the JSX tree. Add/change a variant's
// set here, the component stays untouched.
//
// Note: the legacy "wizard" nav entry was removed from master in a prior batch
// (replaced by the "新建租户" button on TenantListTab). Tenant variant row-3
// ("Wizard") and row-6 ("Tenants 列表") are both spec §4.2 "去除".
const RAIL_CONFIG: Record<RailVariant, RailItem[]> = {
  master: [
    { key: 'notifications', icon: <ChatIcon />,  labelKey: 'admin.nav.management_chat', group: 'ops',    to: '/admin/chat' },
    { key: 'dashboard',     icon: <DashIcon />,  labelKey: 'admin.nav.dashboard',       group: 'ops',    to: '/admin/dashboard' },
    { key: 'proposals',     icon: <BulbIcon />,  labelKey: 'admin.nav.proposals',       group: 'ops',    to: '/admin/proposals' },
    { key: 'dream',         icon: <DreamIcon />, labelKey: 'admin.nav.dream',           group: 'ops',    to: '/admin/dream' },
    { key: 'billing',       icon: <CardIcon />,  labelKey: 'admin.nav.billing',         group: 'config', to: '/admin/billing' },
  ],
  tenant: [
    { key: 'chat',       icon: <ChatIcon />,  labelKey: 'admin.nav.tenant.chat',      group: 'ops',    to: '/admin/chat' },
    { key: 'dashboard',  icon: <DashIcon />,  labelKey: 'admin.nav.tenant.dashboard', group: 'ops',    to: '/admin/dashboard' },
    { key: 'proposals',  icon: <BulbIcon />,  labelKey: 'admin.nav.tenant.proposals', group: 'ops',    to: '/admin/proposals' },
    { key: 'dream',      icon: <DreamIcon />, labelKey: 'admin.nav.dream',            group: 'ops',    to: '/admin/dream' },
    { key: 'billing',    icon: <CardIcon />,  labelKey: 'admin.nav.tenant.billing',   group: 'config', to: '/admin/billing' },
  ],
};

interface AdminRailProps {
  open?: boolean;
  onClose?: () => void;
  /**
   * Hide the "Master" section (租户列表 entry). Used when the rail is
   * rendered inside the tenant-mode view (TenantLayout) where the master
   * cross-tenant navigation is irrelevant.
   *
   * In `variant="tenant"` this value is ignored — the Master section is
   * always suppressed per spec §4.2.
   */
  hideMasterSection?: boolean;
  /**
   * Override the store's `tenantId` for branding. Set when the rail is
   * rendered inside a tenant-scoped iframe (/t/<tid>/admin) so the brand
   * strip reflects the previewed tenant instead of the host session.
   */
  tenantIdOverride?: string;
  /**
   * Icon-set variant (spec §4.2). Defaults to `"master"` so all existing
   * callers see zero behavior change.
   */
  variant?: RailVariant;
}

export function AdminRail({
  open = false,
  onClose,
  hideMasterSection = false,
  tenantIdOverride,
  variant = 'master',
}: AdminRailProps = {}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const storeTenantId = useAdminStore((s) => s.tenantId);
  const tenantId = tenantIdOverride ?? storeTenantId;
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  const isMasterRoute = location.pathname.startsWith('/master/');
  const items = RAIL_CONFIG[variant];
  // Tenant variant forces master-section hidden (spec §4.2 row-6 "去除").
  const showMasterSection = variant === 'master' && !hideMasterSection;

  const handlePick = (key: TabKey) => {
    // `setActiveTab` is typed to the master-variant union; tenant variant
    // introduces the `chat` key which the store will accept at runtime
    // (zustand has no runtime type check). A future pass (T6F.5) will widen
    // `AdminState.activeTab` to include tenant keys; for T6F.3 we stay
    // scope-limited to shell/AdminRail only.
    setActiveTab(key as MasterTabKey);
    // If we're currently on a /master/* route, jump back to legacy shell so the tab is visible
    if (isMasterRoute) navigate('/');
    onClose?.();
  };

  const handleMasterTenants = () => {
    navigate('/master/tenants');
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

  const opsItems = items.filter((i) => i.group === 'ops');
  const configItems = items.filter((i) => i.group === 'config');
  const tenant = tenantId ?? 'mystore';

  return (
    <aside className={`cs-rail ${open ? 'open' : ''}`} data-testid="admin-rail" aria-label={t('admin.nav.aria_label')}>
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

      {showMasterSection && (
        <>
          <div className="cs-nav-sec">{t('admin.nav.section.master')}</div>
          <ul className="cs-nav">
            <li
              data-testid="tab-master-tenants"
              className={`cs-nav-item ${isMasterRoute ? 'active' : ''}`}
              onClick={handleMasterTenants}
              aria-current={isMasterRoute ? 'page' : undefined}
            >
              <TenantsIcon />
              <span className="cs-nav-label">{t('admin.nav.master_tenants')}</span>
            </li>
          </ul>
        </>
      )}

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
