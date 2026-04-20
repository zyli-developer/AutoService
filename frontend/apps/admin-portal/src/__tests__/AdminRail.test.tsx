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

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 't1' });
});

describe('AdminRail', () => {
  it('renders 5 nav items with correct testids', () => {
    renderRail();
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-wizard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
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
    expect(screen.getByTestId('tab-notifications')).toHaveTextContent('管理群');
    expect(screen.getByTestId('tab-wizard')).toHaveTextContent('向导');
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
});
