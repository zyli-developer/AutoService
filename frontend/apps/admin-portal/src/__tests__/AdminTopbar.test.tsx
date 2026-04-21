import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AdminTopbar } from '../components/shell/AdminTopbar';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'acme-corp' });
});

describe('AdminTopbar', () => {
  it('renders tenant label on the left', () => {
    render(<AdminTopbar />);
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('acme-corp');
  });

  it('renders cmdk button and avatar trigger', () => {
    render(<AdminTopbar />);
    expect(screen.getByTestId('btn-cmdk')).toBeInTheDocument();
    expect(screen.getByTestId('avatar-trigger')).toBeInTheDocument();
  });

  it('clicking cmdk opens the command palette overlay', async () => {
    const user = userEvent.setup();
    render(<AdminTopbar />);
    await user.click(screen.getByTestId('btn-cmdk'));
    expect(screen.getByTestId('cmdk-panel')).toBeInTheDocument();
  });

  it('Escape closes the command palette', async () => {
    const user = userEvent.setup();
    render(<AdminTopbar />);
    await user.click(screen.getByTestId('btn-cmdk'));
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('cmdk-panel')).toBeNull();
  });

  // T6F.4 — new props (spec §4.3)
  it('brandName prop replaces the tenant crumb when provided', () => {
    render(<AdminTopbar brandName="AcmeShop" />);
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('AcmeShop');
  });

  it('empty brandName is treated as not provided (flicker guard)', () => {
    render(<AdminTopbar brandName="" />);
    // Falls through to tenantId → 'acme-corp' from beforeEach
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('acme-corp');
  });

  it('authenticatedAs renders inline near the avatar when provided', () => {
    render(<AdminTopbar authenticatedAs="admin@example.com" />);
    const el = screen.getByTestId('topbar-authed-as');
    expect(el).toHaveTextContent('admin@example.com');
  });

  it('empty authenticatedAs renders nothing (flicker guard)', () => {
    render(<AdminTopbar authenticatedAs="" />);
    expect(screen.queryByTestId('topbar-authed-as')).toBeNull();
  });
});
