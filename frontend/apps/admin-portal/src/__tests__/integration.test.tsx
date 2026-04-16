import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfigProvider } from 'antd';
import { App } from '../App';
import { useAdminStore, initialState } from '../store/adminStore';

function renderApp() {
  return render(
    <ConfigProvider>
      <App />
    </ConfigProvider>,
  );
}

beforeEach(() => {
  useAdminStore.setState(initialState);
});

describe('integration', () => {
  it('TC-13: shows LoginPage when not logged in', () => {
    renderApp();
    expect(screen.getByTestId('input-tenant-id')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-workspace')).toBeNull();
  });

  it('TC-14: after login shows AdminWorkspace', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-001');
    await user.click(screen.getByTestId('btn-login'));
    expect(await screen.findByTestId('admin-workspace')).toBeInTheDocument();
  });

  it('TC-15: logout returns to LoginPage', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('admin-workspace');
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-tenant-id')).toBeInTheDocument();
  });
});
