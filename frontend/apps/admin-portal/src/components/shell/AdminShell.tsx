import { useAdminStore } from '../../store/adminStore';
import { AdminTopbar } from './AdminTopbar';
import { AdminRail } from './AdminRail';
import { WizardTab } from '../WizardTab';
import { DashboardTab } from '../DashboardTab';
import { ManagementChat } from '../ManagementChat';
import { ProposalsTab } from '../ProposalsTab';
import { BillingTab } from '../BillingTab';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

const VIEWS: Record<TabKey, React.ComponentType> = {
  notifications: ManagementChat,
  dashboard: DashboardTab,
  wizard: WizardTab,
  proposals: ProposalsTab,
  billing: BillingTab,
};

export function AdminShell() {
  const activeTab = useAdminStore((s) => s.activeTab) as TabKey;
  const View = VIEWS[activeTab];

  return (
    <div className="cs-shell" data-testid="admin-workspace">
      <AdminTopbar />
      <AdminRail />
      <main className="cs-canvas" data-view={activeTab} data-testid="admin-canvas">
        <View />
      </main>
    </div>
  );
}
