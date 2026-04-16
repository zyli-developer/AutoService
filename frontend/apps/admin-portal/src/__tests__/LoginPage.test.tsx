import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginPage } from '../components/LoginPage';
import { useAdminStore } from '../store/adminStore';

describe('LoginPage', () => {
  it('TC-05: renders login form', () => {
    render(<LoginPage />);
    expect(screen.getByTestId('input-tenant-id')).toBeInTheDocument();
    expect(screen.getByTestId('btn-login')).toBeInTheDocument();
  });

  it('TC-06: login with tenant id updates store', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-abc');
    await user.click(screen.getByTestId('btn-login'));
    expect(useAdminStore.getState().isLoggedIn).toBe(true);
    expect(useAdminStore.getState().tenantId).toBe('tenant-abc');
  });

  it('TC-07: empty tenant id does not login', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.click(screen.getByTestId('btn-login'));
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
  });
});
