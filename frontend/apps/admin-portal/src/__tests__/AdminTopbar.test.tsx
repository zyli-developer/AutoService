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
});
