import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfigProvider } from 'antd';
import { App } from '../App';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { _setWSClientImpl } from '../hooks/useOperatorWS';
import { createFakeWSClientClass } from './fakeWSClient';

function renderApp() {
  return render(
    <ConfigProvider>
      <App />
    </ConfigProvider>
  );
}

beforeEach(() => {
  useOperatorStore.setState(initialState);
  _setWSClientImpl(createFakeWSClientClass() as any);
});

describe('integration', () => {
  it('TC-016: shows LoginPage when not logged in', () => {
    renderApp();
    expect(screen.getByTestId('input-operator-id')).toBeInTheDocument();
    expect(screen.queryByTestId('workspace-page')).toBeNull();
  });

  it('TC-017: after login shows WorkspacePage', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    expect(await screen.findByTestId('workspace-page')).toBeInTheDocument();
    expect(screen.queryByTestId('input-operator-id')).toBeNull();
  });

  it('TC-018: adding squad makes tab appear', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    await user.type(screen.getByTestId('input-squad-id'), 'sq-A');
    await user.click(screen.getByTestId('btn-add-squad'));
    expect(await screen.findByTestId('squad-pane-sq-A')).toBeInTheDocument();
  });

  it('TC-019: clicking different tab changes activeSquadId', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    // Add two squads
    await user.type(screen.getByTestId('input-squad-id'), 'sq-A');
    await user.click(screen.getByTestId('btn-add-squad'));
    await user.type(screen.getByTestId('input-squad-id'), 'sq-B');
    await user.click(screen.getByTestId('btn-add-squad'));
    // Click sq-B tab
    const sqBTab = await screen.findByRole('tab', { name: 'sq-B' });
    await user.click(sqBTab);
    expect(useOperatorStore.getState().activeSquadId).toBe('sq-B');
  });

  it('TC-020: clicking logout returns to LoginPage', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-operator-id')).toBeInTheDocument();
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });
});
