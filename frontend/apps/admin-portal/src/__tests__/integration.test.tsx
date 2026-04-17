import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { useAdminStore, initialState } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState(initialState);
});

describe('integration', () => {
  it('TC-13: shows LoginPage when not logged in', () => {
    render(<App />);
    expect(screen.getByTestId('input-tenant-id')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-workspace')).toBeNull();
  });

  it('TC-14: after login shows AdminWorkspace', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-001');
    await user.click(screen.getByTestId('btn-login'));
    expect(await screen.findByTestId('admin-workspace')).toBeInTheDocument();
  });

  it('TC-15: logout returns to LoginPage', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('admin-workspace');
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-tenant-id')).toBeInTheDocument();
  });
});
