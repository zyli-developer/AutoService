import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';
import { AdminTopbar } from './AdminTopbar';
import { AdminRail } from './AdminRail';
import { WizardTab } from '../WizardTab';
import { DashboardTab } from '../DashboardTab';
import { ManagementChat } from '../ManagementChat';
import { ProposalsTab } from '../ProposalsTab';
import { BillingTab } from '../BillingTab';
import { DreamTab } from '../DreamTab';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'dream' | 'billing';

const VIEWS: Record<TabKey, React.ComponentType> = {
  notifications: ManagementChat,
  dashboard: DashboardTab,
  wizard: WizardTab,
  proposals: ProposalsTab,
  dream: DreamTab,
  billing: BillingTab,
};

interface AdminShellProps {
  children?: React.ReactNode;
  viewTag?: string;
  /** Hide the Master tenants nav section (used in TenantLayout). */
  hideMasterSection?: boolean;
  /** Override the store's tenantId for branding (topbar + rail). */
  tenantIdOverride?: string;
}

export function AdminShell({
  children,
  viewTag,
  hideMasterSection,
  tenantIdOverride,
}: AdminShellProps = {}) {
  const { t } = useTranslation();
  const activeTab = useAdminStore((s) => s.activeTab) as TabKey;
  const [navOpen, setNavOpen] = useState(false);
  const View = VIEWS[activeTab];

  const openNav = () => setNavOpen(true);
  const closeNav = () => setNavOpen(false);

  const dataView = viewTag ?? activeTab;

  return (
    <div className="cs-shell" data-testid="admin-workspace">
      <AdminTopbar onToggleNav={openNav} tenantIdOverride={tenantIdOverride} />
      <AdminRail
        open={navOpen}
        onClose={closeNav}
        hideMasterSection={hideMasterSection}
        tenantIdOverride={tenantIdOverride}
      />
      <button
        type="button"
        className={`cs-side-backdrop ${navOpen ? 'on' : ''}`}
        data-testid="cs-side-backdrop"
        aria-label={t('admin.nav.close_menu')}
        onClick={closeNav}
        tabIndex={navOpen ? 0 : -1}
      />
      <main className="cs-canvas" data-view={dataView} data-testid="admin-canvas">
        {children ?? <View />}
      </main>
    </div>
  );
}
