/**
 * T1F.1 · useTenantId tests
 *
 * Covers:
 *  1. Returns tenantId from the path when matched via /t/:tenantId/*
 *  2. Returns `tenant` query parameter when no path param is present
 *  3. Returns null when neither is present
 *  4. Path param wins when both are present (more specific)
 */
import { describe, it, expect } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { renderHook } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

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

  it('returns null when neither path param nor query is set', () => {
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
});
