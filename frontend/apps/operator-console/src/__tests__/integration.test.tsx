import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { App } from '../App';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { _setWSClientImpl } from '../hooks/useOperatorWS';
import { createFakeWSClientClass } from './fakeWSClient';

beforeEach(() => {
  useOperatorStore.setState(initialState);
  _setWSClientImpl(createFakeWSClientClass() as any);
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Mock a successful POST /api/auth/operator/dev-login for UI-login tests. */
function mockDevLoginOk(operatorId = 'op-001', tenantId = 'tenant_test') {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      ok: true,
      redirect: '/operator',
      operator_id: operatorId,
      tenant_id: tenantId,
      email: 'op@dev.local',
    }),
  }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

/** Shortcut: bypass the UI and flip the store to a logged-in state. */
function forceLoggedIn(operatorId = 'op-001') {
  useOperatorStore.getState().login(operatorId, '');
}

// Wrap <App /> in a tenant-scoped route so WorkspacePage's useTenantId()
// resolves (T1F.4). Operator console now expects /t/:tenantId/operator.
function renderApp(initialPath = '/t/tenant_test/operator') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/t/:tenantId/operator" element={<App />} />
        <Route path="/" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('integration', () => {
  it('TC-016: shows LoginPage when not logged in', () => {
    renderApp();
    expect(screen.getByTestId('input-email')).toBeInTheDocument();
    expect(screen.queryByTestId('workspace-page')).toBeNull();
  });

  it('TC-017: after successful dev-login shows WorkspacePage', async () => {
    mockDevLoginOk('op-001', 'tenant_test');
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByTestId('input-email'), 'op@dev.local');
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant_test');
    await user.click(screen.getByTestId('btn-login'));
    expect(await screen.findByTestId('workspace-page')).toBeInTheDocument();
    expect(screen.queryByTestId('input-email')).toBeNull();
  });

  it('TC-018: adding squad makes channel appear in sidebar', async () => {
    const user = userEvent.setup();
    forceLoggedIn('op-001');
    renderApp();
    await screen.findByTestId('workspace-page');
    await user.type(screen.getByTestId('input-squad-id'), 'sq-A');
    await user.click(screen.getByTestId('btn-add-squad'));
    expect(await screen.findByTestId('channel-sq-A')).toBeInTheDocument();
  });

  it('TC-019: clicking different channel changes activeSquadId', async () => {
    const user = userEvent.setup();
    forceLoggedIn('op-001');
    renderApp();
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
    forceLoggedIn('op-001');
    renderApp();
    await screen.findByTestId('workspace-page');
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-email')).toBeInTheDocument();
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });
});
