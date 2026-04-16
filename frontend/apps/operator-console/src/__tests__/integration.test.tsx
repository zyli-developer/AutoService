import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { _setWSClientImpl } from '../hooks/useOperatorWS';
import { createFakeWSClientClass } from './fakeWSClient';

beforeEach(() => {
  useOperatorStore.setState(initialState);
  _setWSClientImpl(createFakeWSClientClass() as any);
});

describe('integration', () => {
  it('TC-016: shows LoginPage when not logged in', () => {
    render(<App />);
    expect(screen.getByTestId('input-operator-id')).toBeInTheDocument();
    expect(screen.queryByTestId('workspace-page')).toBeNull();
  });

  it('TC-017: after login shows WorkspacePage', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    expect(await screen.findByTestId('workspace-page')).toBeInTheDocument();
    expect(screen.queryByTestId('input-operator-id')).toBeNull();
  });

  it('TC-018: adding squad makes channel appear in sidebar', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    await user.type(screen.getByTestId('input-squad-id'), 'sq-A');
    await user.click(screen.getByTestId('btn-add-squad'));
    expect(await screen.findByTestId('channel-sq-A')).toBeInTheDocument();
  });

  it('TC-019: clicking different channel changes activeSquadId', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    await user.type(screen.getByTestId('input-squad-id'), 'sq-A');
    await user.click(screen.getByTestId('btn-add-squad'));
    await user.type(screen.getByTestId('input-squad-id'), 'sq-B');
    await user.click(screen.getByTestId('btn-add-squad'));
    await user.click(screen.getByTestId('channel-sq-B'));
    expect(useOperatorStore.getState().activeSquadId).toBe('sq-B');
  });

  it('TC-020: clicking logout returns to LoginPage', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('workspace-page');
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-operator-id')).toBeInTheDocument();
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });
});
