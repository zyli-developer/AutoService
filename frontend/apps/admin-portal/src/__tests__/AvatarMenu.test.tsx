import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AvatarMenu } from '../components/shell/AvatarMenu';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
});

describe('AvatarMenu', () => {
  it('shows closed trigger with first initial of tenant id', () => {
    render(<AvatarMenu />);
    const btn = screen.getByTestId('avatar-trigger');
    expect(btn).toHaveTextContent('t');
    expect(screen.queryByTestId('avatar-menu')).toBeNull();
  });

  it('opens menu on click and exposes tenant-id + btn-logout', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    expect(screen.getByTestId('avatar-menu')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-001');
    expect(screen.getByTestId('btn-logout')).toBeInTheDocument();
  });

  it('btn-logout clears login state', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
  });

  it('falls back to "?" when tenantId is null', () => {
    useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: null });
    render(<AvatarMenu />);
    expect(screen.getByTestId('avatar-trigger')).toHaveTextContent('?');
  });
});
