import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AdminWorkspace } from '../components/AdminWorkspace';
import { useAdminStore, initialState } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
});

describe('AdminWorkspace', () => {
  it('TC-08: renders workspace with tenant id', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('admin-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-001');
  });

  it('TC-09: shows 4 tabs', () => {
    render(<AdminWorkspace />);
    expect(screen.getByRole('tab', { name: '\u5411\u5BFC' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '\u4EEA\u8868\u76D8' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '\u901A\u77E5' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '\u63D0\u6848' })).toBeInTheDocument();
  });

  it('TC-10: default tab is wizard', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('tab-wizard')).toBeInTheDocument();
  });

  it('TC-11: clicking dashboard tab switches content', async () => {
    const user = userEvent.setup();
    render(<AdminWorkspace />);
    await user.click(screen.getByRole('tab', { name: '\u4EEA\u8868\u76D8' }));
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
  });

  it('TC-12: logout button resets state', async () => {
    const user = userEvent.setup();
    render(<AdminWorkspace />);
    await user.click(screen.getByTestId('btn-logout'));
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
  });
});
