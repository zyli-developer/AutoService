import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { WorkspacePage, buildOperatorWsUrl } from '../components/WorkspacePage';
import { useTenantId } from '../hooks/useTenantId';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { useOperatorWS, _setWSClientImpl } from '../hooks/useOperatorWS';
import { createFakeWSClientClass, fakeInstance } from './fakeWSClient';

// Heavy/irrelevant subtrees mocked so the test focuses on routing + WS wiring.
vi.mock('../components/IMTitlebar', () => ({ IMTitlebar: () => <div data-testid="im-titlebar" /> }));
vi.mock('../components/IMSidebar', () => ({ IMSidebar: () => <aside data-testid="im-sidebar" /> }));
vi.mock('../components/ConversationFeed', () => ({ ConversationFeed: () => <div data-testid="conv-feed" /> }));
vi.mock('../components/CopilotView', () => ({ CopilotView: () => <div data-testid="copilot" /> }));
vi.mock('../components/IMInput', () => ({ IMInput: () => <div data-testid="im-input" /> }));

beforeEach(() => {
  useOperatorStore.setState(initialState);
  _setWSClientImpl(createFakeWSClientClass() as any);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('buildOperatorWsUrl', () => {
  it('TC-TEN-01: builds a tenant-scoped WS URL with query param', () => {
    const url = buildOperatorWsUrl('tenant_foo', 'example.com');
    expect(url).toBe('ws://example.com:8000/ws/operator?tenant=tenant_foo');
  });

  it('TC-TEN-02: URL-encodes unsafe tenant ids', () => {
    const url = buildOperatorWsUrl('a/b c', 'host');
    expect(url).toBe('ws://host:8000/ws/operator?tenant=a%2Fb%20c');
  });
});

describe('useTenantId', () => {
  function Probe() {
    const tid = useTenantId();
    return <span data-testid="tid">{tid ?? 'NONE'}</span>;
  }

  it('TC-TEN-03: reads tenantId from route path param', () => {
    render(
      <MemoryRouter initialEntries={['/t/acme/operator']}>
        <Routes>
          <Route path="/t/:tenantId/operator" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('tid').textContent).toBe('acme');
  });

  it('TC-TEN-04: returns null when no tenant is present', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('tid').textContent).toBe('NONE');
  });
});

describe('WorkspacePage tenant wiring', () => {
  it('TC-TEN-05: renders no-tenant fallback when the route has no :tenantId', () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('no-tenant-fallback')).toBeInTheDocument();
    // No WS should have been created in the fallback state.
    expect(fakeInstance).toBeNull();
  });

  it('TC-TEN-06: passes tenant-scoped WS URL into useOperatorWS when route carries :tenantId', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(
      <MemoryRouter initialEntries={['/t/tenant_foo/operator']}>
        <Routes>
          <Route path="/t/:tenantId/operator" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('workspace-page')).toBeInTheDocument();
    // The fake WS client should have been constructed with the tenant-aware URL.
    expect(fakeInstance).not.toBeNull();
    expect(fakeInstance!.url).toBe('ws://localhost:8000/ws/operator?tenant=tenant_foo');
    // Flip to open to cover the effect path.
    await act(async () => {
      fakeInstance!.triggerOpen();
    });
    expect(useOperatorStore.getState().wsStatus).toBe('open');
  });
});

describe('useOperatorWS guard', () => {
  function Harness({ url }: { url: string }) {
    useOperatorWS(url);
    return <div />;
  }
  it('TC-TEN-07: does not open a WS when url is empty (no tenant)', () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(<Harness url="" />);
    expect(fakeInstance).toBeNull();
  });
});
