/**
 * T1F.3 — tenant-aware routing + WS URL
 *
 * These tests cover the routing contract introduced by T1F.3:
 *   1. `/t/:tenantId/chat` renders the chat UI
 *   2. A URL with no resolvable tenant renders a "select tenant" fallback
 *   3. The WebSocket URL includes `?tenant=<tenantId>` (observed via the
 *      mocked WSClient constructor)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { WSClientOptions } from '@autoservice/ws-client';
import { useChatStore, initialState } from './store/chatStore';

const wsConstructorCalls: WSClientOptions[] = [];

vi.mock('@autoservice/ws-client', async (importActual) => {
  const actual = await importActual<typeof import('@autoservice/ws-client')>();
  return {
    ...actual,
    WSClient: class {
      constructor(opts: WSClientOptions) {
        wsConstructorCalls.push(opts);
        Object.assign(this, {
          connect: () => {},
          send: () => Promise.resolve(),
          close: () => {},
        });
      }
    },
  };
});

const { App } = await import('./App');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/t/:tenantId/chat" element={<App />} />
        <Route path="/chat" element={<App />} />
        <Route path="*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('T1F.3 tenant-aware routing', () => {
  beforeEach(() => {
    wsConstructorCalls.length = 0;
    useChatStore.setState(initialState);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('renders chat UI when URL is /t/tenant_foo/chat', () => {
    renderAt('/t/tenant_foo/chat');
    // MerchantSite only mounts inside ChatApp — so its logo is a stable
    // "chat UI is live" signal that doesn't depend on ChatFAB internals.
    expect(screen.getByTestId('merchant-logo')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-fallback')).toBeNull();
  });

  it('shows the tenant fallback when no tenant is present', () => {
    renderAt('/');
    expect(screen.getByTestId('tenant-fallback')).toBeInTheDocument();
    // MerchantSite must NOT mount — otherwise ChatApp is running and the
    // WSClient will have been constructed against a bogus URL.
    expect(screen.queryByTestId('merchant-logo')).toBeNull();
    // And no WS client should have been constructed.
    expect(wsConstructorCalls).toHaveLength(0);
  });

  it('builds WS URL with ?tenant=<tenantId> from the path param', () => {
    renderAt('/t/tenant_foo/chat');
    expect(wsConstructorCalls).toHaveLength(1);
    const { url } = wsConstructorCalls[0];
    // Path component must target /ws/customer (not a hardcoded /ws/customer/<id>)
    expect(url).toMatch(/\/ws\/customer(\?|$)/);
    // Tenant is carried as a query-string parameter
    expect(url).toContain('tenant=tenant_foo');
    // Must NOT hardcode localhost:8000 anymore
    expect(url).not.toContain('localhost:8000');
  });

  it('accepts /chat?tenant=<id> as fork-side fallback route', () => {
    renderAt('/chat?tenant=tenant_bar');
    expect(screen.getByTestId('merchant-logo')).toBeInTheDocument();
    expect(wsConstructorCalls).toHaveLength(1);
    expect(wsConstructorCalls[0].url).toContain('tenant=tenant_bar');
  });

  it('URL-encodes tenant ids with special characters', () => {
    renderAt('/t/acme%20corp/chat');
    expect(wsConstructorCalls).toHaveLength(1);
    // The raw value decoded by the router is "acme corp"; re-encoded it becomes acme%20corp
    expect(wsConstructorCalls[0].url).toContain('tenant=acme%20corp');
  });
});
