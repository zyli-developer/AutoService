/**
 * T6F.1 · useTenantId tests (M2 real impl)
 *
 * Covers:
 *  1. Returns tenantId from the path when matched via /t/:tenantId/*
 *  2. Returns `tenant` query parameter when no path param is present
 *  3. Returns null when neither URL source nor session provides a tenant
 *  4. Path param wins over query string (more specific)
 *  5. Falls back to session.tenant_id when mode === 'tenant' and URL empty
 *  6. Returns null when mode === 'master' + URL has no tenant scope
 *  7. URL path param wins over session.tenant_id (URL is authoritative)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// Mock useSessionMode before importing useTenantId.
const useSessionModeMock = vi.fn();
vi.mock('./useSessionMode', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

import { useTenantId } from './useTenantId';

function makeWrapper(entry: string, routePath: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      MemoryRouter,
      { initialEntries: [entry] },
      createElement(
        Routes,
        null,
        createElement(Route, { path: routePath, element: children as any })
      )
    );
  };
}

// Default: no session (anon master) — matches M1 behaviour.
beforeEach(() => {
  useSessionModeMock.mockReset();
  useSessionModeMock.mockReturnValue({
    data: null,
    loading: false,
    error: null,
    refetch: () => {},
  });
});

describe('useTenantId', () => {
  it('returns tenantId from the URL path (/t/:tenantId/chat)', () => {
    const wrapper = makeWrapper('/t/tenant_abc/chat', '/t/:tenantId/chat');
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBe('tenant_abc');
  });

  it('returns tenant from the query string when path param is absent', () => {
    const wrapper = makeWrapper('/chat?tenant=tenant_abc', '/chat');
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBe('tenant_abc');
  });

  it('returns null when neither URL nor session provides a tenant', () => {
    const wrapper = makeWrapper('/chat', '/chat');
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBeNull();
  });

  it('prefers the path param over the query string when both are set', () => {
    const wrapper = makeWrapper(
      '/t/tenant_from_path/chat?tenant=tenant_from_query',
      '/t/:tenantId/chat'
    );
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBe('tenant_from_path');
  });

  it('falls back to session.tenant_id when mode=tenant and URL has no scope', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'tenant',
        tenant_id: 'acme',
        authenticated: true,
        authenticated_as: 'admin@acme.com',
        tier: 1,
        brand_name: 'Acme',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const wrapper = makeWrapper('/admin', '/admin');
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBe('acme');
  });

  it('returns null when mode=master and URL has no tenant scope', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'platform@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const wrapper = makeWrapper('/admin', '/admin');
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBeNull();
  });

  it('URL path param wins over session.tenant_id (URL is authoritative)', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'tenant',
        tenant_id: 'session_tid',
        authenticated: true,
        authenticated_as: 'admin@acme.com',
        tier: 1,
        brand_name: 'Acme',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const wrapper = makeWrapper(
      '/t/url_tid/admin',
      '/t/:tenantId/admin'
    );
    const { result } = renderHook(() => useTenantId(), { wrapper });
    expect(result.current).toBe('url_tid');
  });
});
