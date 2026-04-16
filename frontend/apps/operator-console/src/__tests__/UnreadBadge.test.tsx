import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { IMSidebar } from '../components/IMSidebar';
import { vi } from 'vitest';

beforeEach(() => {
  useOperatorStore.setState({ ...initialState });
});

describe('Unread badges in IMSidebar', () => {
  it('TC-01: badge hidden when unreadCounts is 0', () => {
    useOperatorStore.setState({
      operatorId: 'op-1',
      squads: ['sq-A'],
      activeSquadId: 'sq-A',
    });
    render(<IMSidebar onLogout={vi.fn()} />);
    expect(screen.queryByTestId('unread-badge-sq-A')).toBeNull();
  });

  it('TC-02: badge shows count when > 0', () => {
    useOperatorStore.setState({
      operatorId: 'op-1',
      squads: ['sq-A'],
      activeSquadId: 'sq-A',
    });
    useOperatorStore.getState().incrementUnread('sq-A');
    useOperatorStore.getState().incrementUnread('sq-A');
    useOperatorStore.getState().incrementUnread('sq-A');
    render(<IMSidebar onLogout={vi.fn()} />);
    const badge = screen.getByTestId('unread-badge-sq-A');
    expect(badge).toHaveTextContent('3');
  });

  it('TC-03: clearUnread resets count', () => {
    useOperatorStore.getState().incrementUnread('sq-B');
    useOperatorStore.getState().incrementUnread('sq-B');
    useOperatorStore.getState().clearUnread('sq-B');
    expect(useOperatorStore.getState().unreadCounts['sq-B']).toBe(0);
  });
});
