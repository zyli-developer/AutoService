import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConversationFeed, customerDisplayName } from '../components/ConversationFeed';
import { useOperatorStore, initialState, type Conversation } from '../store/operatorStore';

const makeConv = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: 'conv-001',
  squadId: 'sq-A',
  customerId: 'cust-alice',
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

describe('ConversationFeed cards', () => {
  it('TC-14: displays generated customer display name in im-card', () => {
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv() },
    });
    render(<ConversationFeed squadId="sq-A" />);
    expect(screen.getByTestId('conv-customer-id').textContent).toMatch(
      /^\s*customer-[a-z]+-[a-z]+\s*$/,
    );
  });

  it('customerDisplayName is deterministic per customerId', () => {
    expect(customerDisplayName('cust-alice')).toBe(customerDisplayName('cust-alice'));
    expect(customerDisplayName('cust-alice')).not.toBe(customerDisplayName('cust-bob'));
    expect(customerDisplayName('cust-alice')).toMatch(/^customer-[a-z]+-[a-z]+$/);
  });

  it('TC-15: displays last message truncated at 40 chars', () => {
    const longMsg = 'A'.repeat(50);
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv({ lastMessage: longMsg }) },
    });
    render(<ConversationFeed squadId="sq-A" />);
    const el = screen.getByTestId('conv-last-message');
    expect(el.textContent!.length).toBeLessThanOrEqual(41);
    expect(el.textContent).toContain('…');
  });

  it('TC-15b: short message not truncated', () => {
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv({ lastMessage: 'Hello' }) },
    });
    render(<ConversationFeed squadId="sq-A" />);
    expect(screen.getByTestId('conv-last-message')).toHaveTextContent('Hello');
  });

  it('TC-09 (partial): click triggers onCardClick', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv() },
    });
    render(<ConversationFeed squadId="sq-A" onCardClick={onClick} />);
    await user.click(screen.getByTestId('conv-card-conv-001'));
    expect(onClick).toHaveBeenCalledWith('conv-001');
  });

  it('displays correct status tag for idle', () => {
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv({ mode: 'auto', lastMessageSender: '' }) },
    });
    render(<ConversationFeed squadId="sq-A" />);
    expect(screen.getByTestId('conv-status-tag')).toHaveTextContent('空闲');
  });

  it('displays correct status tag for human-takeover', () => {
    useOperatorStore.setState({
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    render(<ConversationFeed squadId="sq-A" />);
    expect(screen.getByTestId('conv-status-tag')).toHaveTextContent('人工接管');
  });
});
