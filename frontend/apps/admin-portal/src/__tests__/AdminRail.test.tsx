import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AdminRail } from '../components/shell/AdminRail';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 't1' });
});

describe('AdminRail', () => {
  it('renders 5 nav items with correct testids', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-wizard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
  });

  it('default active item is notifications', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toHaveClass('active');
    expect(screen.getByTestId('tab-dashboard')).not.toHaveClass('active');
  });

  it('clicking an item switches active tab in store', async () => {
    const user = userEvent.setup();
    render(<AdminRail />);
    await user.click(screen.getByTestId('tab-dashboard'));
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
    expect(screen.getByTestId('tab-dashboard')).toHaveClass('active');
  });

  it('each item exposes a tooltip label', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toHaveTextContent('管理群');
    expect(screen.getByTestId('tab-wizard')).toHaveTextContent('向导');
  });
});
