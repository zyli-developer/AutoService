/**
 * T1F.6 · TenantPreviewTab tests.
 *
 * Covers:
 *   - iframe src uses `/t/<id>/chat`
 *   - top bar shows tenant id and back-to-list link
 *   - URL-unsafe tenant ids are percent-encoded
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TenantPreviewTab } from '../TenantPreviewTab';

function renderWithTenant(tenantId: string) {
  return render(
    <MemoryRouter initialEntries={[`/master/tenants/${tenantId}/preview`]}>
      <Routes>
        <Route path="/master/tenants/:id/preview" element={<TenantPreviewTab />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('TenantPreviewTab', () => {
  it('TC-001: renders the top bar with tenant id and back link', () => {
    renderWithTenant('acme');
    expect(screen.getByTestId('tenant-preview-topbar')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-preview-id')).toHaveTextContent('acme');
    expect(screen.getByTestId('tenant-preview-back')).toHaveAttribute('href', '/master/tenants');
  });

  it('TC-002: embeds /t/<id>/chat in an iframe', () => {
    renderWithTenant('globex');
    const iframe = screen.getByTestId('tenant-preview-iframe') as HTMLIFrameElement;
    expect(iframe.tagName).toBe('IFRAME');
    expect(iframe.getAttribute('src')).toBe('/t/globex/chat');
  });

  it('TC-003: iframe has a title referencing the tenant', () => {
    renderWithTenant('acme');
    const iframe = screen.getByTestId('tenant-preview-iframe') as HTMLIFrameElement;
    expect(iframe.getAttribute('title')).toContain('acme');
  });

  it('TC-004: percent-encodes URL-unsafe tenant ids', () => {
    renderWithTenant('a%2Fb'); // "a/b" once decoded by the router
    // useParams returns the decoded id ("a/b"); encodeURIComponent re-encodes for the href.
    const iframe = screen.getByTestId('tenant-preview-iframe') as HTMLIFrameElement;
    expect(iframe.getAttribute('src')).toBe('/t/a%2Fb/chat');
  });

  it('TC-005: "open in new tab" link points at the same chat path', () => {
    renderWithTenant('acme');
    const link = screen.getByTestId('tenant-preview-open-new');
    expect(link.getAttribute('href')).toBe('/t/acme/chat');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });
});
