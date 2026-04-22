import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { useAdminStore, initialState } from '../store/adminStore';
import { AdminRail } from '../components/shell/AdminRail';

const renderRail = (path = '/') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AdminRail />
    </MemoryRouter>,
  );

const renderRailVariant = (variant: 'master' | 'tenant', path = '/') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AdminRail variant={variant} />
    </MemoryRouter>,
  );

beforeEach(() => {
  useAdminStore.setState({ ...initialState, tenantId: 't1' });
});

describe('AdminRail', () => {
  it('renders ops and config nav items (wizard entry moved to TenantListTab)', () => {
    renderRail();
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
    // The legacy "向导" item was removed — new-tenant creation now happens
    // via the "新建租户" button on /master/tenants.
    expect(screen.queryByTestId('tab-wizard')).not.toBeInTheDocument();
  });

  it('default active item is notifications', () => {
    renderRail();
    expect(screen.getByTestId('tab-notifications')).toHaveClass('active');
    expect(screen.getByTestId('tab-dashboard')).not.toHaveClass('active');
  });

  it('clicking an item switches active tab in store', async () => {
    const user = userEvent.setup();
    renderRail();
    await user.click(screen.getByTestId('tab-dashboard'));
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
    expect(screen.getByTestId('tab-dashboard')).toHaveClass('active');
  });

  it('each item exposes a tooltip label', () => {
    renderRail();
    // Note: i18n isn't initialized in this test env (known pre-existing
    // issue); accept either the resolved Chinese label or the unresolved
    // translation key — same pattern used for tab-master-tenants below.
    expect(screen.getByTestId('tab-notifications').textContent).toMatch(
      /(管理群|admin\.nav\.management_chat|Management)/,
    );
  });

  it('renders the Master tenants nav item', () => {
    renderRail();
    const master = screen.getByTestId('tab-master-tenants');
    expect(master).toBeInTheDocument();
    // Note: i18n isn't initialized in this test env (known pre-existing issue);
    // verify the label key renders, test env returns it unresolved.
    expect(master.textContent).toMatch(/(master_tenants|租户列表|Tenants)/);
  });

  it('highlights Master item when on /master/* route', () => {
    renderRail('/master/tenants');
    expect(screen.getByTestId('tab-master-tenants')).toHaveClass('active');
  });

  it('does not highlight Master item on legacy /', () => {
    renderRail('/');
    expect(screen.getByTestId('tab-master-tenants')).not.toHaveClass('active');
  });

  // ---- T6F.3 variant prop (spec §4.2) ----

  describe('variant prop (spec §4.2)', () => {
    it('default variant is master and renders existing icons (back-compat)', () => {
      // No `variant` prop → same icon set as M1 baseline. This is the
      // "variant={undefined} === variant=master" contract.
      renderRail();
      expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
      expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
      expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
      expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
      // Master-specific entries present:
      expect(screen.getByTestId('tab-master-tenants')).toBeInTheDocument();
      // Tenant-only keys MUST NOT leak into the default (master) variant:
      expect(screen.queryByTestId('tab-chat')).not.toBeInTheDocument();
    });

    it('tenant variant renders 4 tab icons (Chat / Dashboard / Proposals / Billing)', () => {
      renderRailVariant('tenant');
      expect(screen.getByTestId('tab-chat')).toBeInTheDocument();
      expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
      expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
      expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
      // Master-only entries suppressed (spec §4.2 rows 3 & 6 "去除"):
      expect(screen.queryByTestId('tab-master-tenants')).not.toBeInTheDocument();
      expect(screen.queryByTestId('tab-notifications')).not.toBeInTheDocument();
      expect(screen.queryByTestId('tab-wizard')).not.toBeInTheDocument();
    });

    it('tenant variant labels match spec §4.2', () => {
      renderRailVariant('tenant');
      // i18n not initialized in test env; accept either resolved CN/EN or
      // unresolved key (same pattern as existing master-variant tests).
      expect(screen.getByTestId('tab-chat').textContent).toMatch(
        /(admin\.nav\.tenant\.chat|Chat|对话|管理对话)/,
      );
      expect(screen.getByTestId('tab-dashboard').textContent).toMatch(
        /(admin\.nav\.tenant\.dashboard|Dashboard|仪表)/,
      );
      expect(screen.getByTestId('tab-proposals').textContent).toMatch(
        /(admin\.nav\.tenant\.proposals|Proposals|提案)/,
      );
      expect(screen.getByTestId('tab-billing').textContent).toMatch(
        /(admin\.nav\.tenant\.billing|Billing|账单)/,
      );
    });

    it('tenant variant preserves active-highlight behavior on click', async () => {
      const user = userEvent.setup();
      renderRailVariant('tenant');
      // Initial: no item active (store default activeTab='notifications' which
      // does not match any tenant key — so none should have .active).
      expect(screen.getByTestId('tab-dashboard')).not.toHaveClass('active');
      await user.click(screen.getByTestId('tab-dashboard'));
      // Click flips store.activeTab; rail re-reads and highlights.
      expect(useAdminStore.getState().activeTab).toBe('dashboard');
      expect(screen.getByTestId('tab-dashboard')).toHaveClass('active');
    });

    it('tenant variant ignores hideMasterSection and still hides Master section', () => {
      // hideMasterSection=false normally shows master-tenants in master variant,
      // but tenant variant forces it hidden regardless.
      render(
        <MemoryRouter initialEntries={['/']}>
          <AdminRail variant="tenant" hideMasterSection={false} />
        </MemoryRouter>,
      );
      expect(screen.queryByTestId('tab-master-tenants')).not.toBeInTheDocument();
    });
  });
});
