import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SquadPane } from '../components/SquadPane';
import { useOperatorStore, initialState, type Conversation } from '../store/operatorStore';

const makeConv = (overrides: Partial<Conversation>): Conversation => ({
  id: 'conv-001',
  squadId: 'sq-A',
  customerId: 'cust-001',
  mode: 'auto',
  state: 'active',
  lastMessage: '',
  lastMessageSender: '',
  lastActivityTs: '2026-04-16T10:00:00Z',
  ...overrides,
});

beforeEach(() => {
  useOperatorStore.setState({ ...initialState, conversations: {} });
});

describe('SquadPane', () => {
  it('TC-01: empty squad shows placeholder', () => {
    render(<SquadPane squadId="sq-A" />);
    expect(screen.getByTestId('empty-squad')).toHaveTextContent('暂无会话');
  });

  it('TC-08: filters conversations by squadId', () => {
    useOperatorStore.setState({
      conversations: {
        'c1': makeConv({ id: 'c1', squadId: 'sq-A' }),
        'c2': makeConv({ id: 'c2', squadId: 'sq-B' }),
        'c3': makeConv({ id: 'c3', squadId: 'sq-A' }),
      },
    });
    render(<SquadPane squadId="sq-A" />);
    expect(screen.getByTestId('conv-card-c1')).toBeInTheDocument();
    expect(screen.getByTestId('conv-card-c3')).toBeInTheDocument();
    expect(screen.queryByTestId('conv-card-c2')).toBeNull();
  });

  it('TC-09: onCardClick called with conversationId', async () => {
    const onClick = vi.fn();
    useOperatorStore.setState({
      conversations: {
        'c1': makeConv({ id: 'c1', squadId: 'sq-A' }),
      },
    });
    const user = userEvent.setup();
    render(<SquadPane squadId="sq-A" onCardClick={onClick} />);
    await user.click(screen.getByTestId('conv-card-c1'));
    expect(onClick).toHaveBeenCalledWith('c1');
  });

  it('TC-10: cards sorted by lastActivityTs descending', () => {
    useOperatorStore.setState({
      conversations: {
        'c-old': makeConv({ id: 'c-old', squadId: 'sq-A', lastActivityTs: '2026-04-16T08:00:00Z' }),
        'c-new': makeConv({ id: 'c-new', squadId: 'sq-A', lastActivityTs: '2026-04-16T12:00:00Z' }),
        'c-mid': makeConv({ id: 'c-mid', squadId: 'sq-A', lastActivityTs: '2026-04-16T10:00:00Z' }),
      },
    });
    render(<SquadPane squadId="sq-A" />);
    const pane = screen.getByTestId('squad-pane-sq-A');
    const cards = within(pane).getAllByTestId(/^conv-card-/);
    expect(cards[0].dataset.testid).toBe('conv-card-c-new');
    expect(cards[1].dataset.testid).toBe('conv-card-c-mid');
    expect(cards[2].dataset.testid).toBe('conv-card-c-old');
  });
});
