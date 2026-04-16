import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useOperatorStore } from '../store/operatorStore';
import { ConcurrencyWarning } from '../components/ConcurrencyWarning';
import type { Conversation } from '../store/operatorStore';

const makeConv = (id: string, state: Conversation['state'] = 'active'): Conversation => ({
  id,
  squadId: 'sq-A',
  customerId: `cust-${id}`,
  mode: 'auto',
  state,
  lastMessage: '',
  lastMessageSender: '',
  lastActivityTs: '2026-04-16T10:00:00Z',
});

describe('ConcurrencyWarning', () => {
  it('TC-01: not shown when conversations count < limit', () => {
    useOperatorStore.setState({ concurrencyLimit: 5 });
    useOperatorStore.getState().addConversation(makeConv('c1'));
    const { container } = render(<ConcurrencyWarning />);
    expect(container.innerHTML).toBe('');
  });

  it('TC-02: shown when conversations count >= limit', () => {
    useOperatorStore.setState({ concurrencyLimit: 2 });
    useOperatorStore.getState().addConversation(makeConv('c1'));
    useOperatorStore.getState().addConversation(makeConv('c2'));
    render(<ConcurrencyWarning />);
    expect(screen.getByTestId('concurrency-warning')).toBeInTheDocument();
  });

  it('TC-03: displays correct count and limit numbers', () => {
    useOperatorStore.setState({ concurrencyLimit: 3 });
    useOperatorStore.getState().addConversation(makeConv('c1'));
    useOperatorStore.getState().addConversation(makeConv('c2'));
    useOperatorStore.getState().addConversation(makeConv('c3'));
    render(<ConcurrencyWarning />);
    expect(screen.getByTestId('concurrency-warning')).toHaveTextContent(
      '并发会话已达上限 (3/3)',
    );
  });
});
