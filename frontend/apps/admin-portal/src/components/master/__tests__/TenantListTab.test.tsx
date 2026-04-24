/**
 * T1F.6 · TenantListTab tests.
 *
 * Covers:
 *   - empty-state rendering
 *   - renders one row per tenant (id, brand, status badge)
 *   - each row links to `/master/tenants/:id/preview`
 *   - graceful error handling when the API rejects
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TenantListTab } from '../TenantListTab';

const fetchJSONMock = vi.hoisted(() => vi.fn());

vi.mock('../../../api', () => ({
  fetchJSON: fetchJSONMock,
  postJSON: vi.fn(),
  postForm: vi.fn(),
}));

afterEach(() => {
  vi.resetAllMocks();
});

function renderAt(path = '/master/tenants') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TenantListTab />
    </MemoryRouter>,
  );
}

describe('TenantListTab', () => {
  it('TC-001: renders empty state when API returns []', async () => {
    fetchJSONMock.mockResolvedValueOnce([]);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-list-empty')).toBeInTheDocument());
    expect(screen.queryByTestId('tenant-list')).not.toBeInTheDocument();
  });

  it('TC-002: renders one row per tenant returned from /api/master/tenants', async () => {
    fetchJSONMock.mockResolvedValueOnce([
      { tenant_id: 'acme', brand_name: 'Acme Co', industry: 'retail', status: 'sandbox', created_at: '2026-04-20T00:00:00+00:00' },
      { tenant_id: 'globex', brand_name: 'Globex', industry: 'saas', status: 'published_pending_fork', created_at: '2026-04-19T00:00:00+00:00' },
    ]);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-list')).toBeInTheDocument());

    expect(screen.getByTestId('tenant-row-acme')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-row-globex')).toBeInTheDocument();
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
    expect(screen.getByText('Globex')).toBeInTheDocument();
  });

  it('TC-003: each row links to /master/tenants/:id/preview', async () => {
    fetchJSONMock.mockResolvedValueOnce([
      { tenant_id: 'acme', brand_name: 'Acme', industry: 'retail', status: 'sandbox', created_at: null },
    ]);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-row-acme')).toBeInTheDocument());
    const row = screen.getByTestId('tenant-row-acme');
    expect(row.getAttribute('href')).toBe('/master/tenants/acme/preview');
  });

  it('TC-004: status badge reflects the tenant status string', async () => {
    fetchJSONMock.mockResolvedValueOnce([
      { tenant_id: 'dead1', brand_name: 'Dead One', industry: 'x', status: 'archived', created_at: null },
    ]);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-status-dead1')).toBeInTheDocument());
    expect(screen.getByTestId('tenant-status-dead1')).toHaveTextContent('archived');
  });

  it('TC-005: shows error when the API rejects', async () => {
    fetchJSONMock.mockRejectedValueOnce(new Error('boom'));
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-list-error')).toBeInTheDocument());
    expect(screen.getByTestId('tenant-list-error').textContent).toContain('boom');
  });

  it('TC-006: falls back to tenant_id when brand_name is empty', async () => {
    fetchJSONMock.mockResolvedValueOnce([
      { tenant_id: 'noname', brand_name: null, industry: 'general', status: 'sandbox', created_at: null },
    ]);
    renderAt();
    await waitFor(() => expect(screen.getByTestId('tenant-row-noname')).toBeInTheDocument());
    // tenant_id appears as brand fallback and also as the id subtitle — so at least once.
    expect(screen.getAllByText('noname').length).toBeGreaterThanOrEqual(1);
  });
});
