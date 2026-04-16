import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConversationCard } from '../components/ConversationCard';
import type { Conversation } from '../store/operatorStore';

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

describe('ConversationCard', () => {
  it('TC-14: displays conversation_id (short) and customer_id', () => {
    render(
      <ConversationCard conversation={makeConv({ id: 'conv-abcdefghijk-long-id' })} />,
    );
    expect(screen.getByTestId('conv-customer-id')).toHaveTextContent('cust-alice');
    expect(screen.getByTestId('conv-id')).toHaveTextContent('conv-abc…');
  });

  it('TC-15: displays last message truncated at 40 chars', () => {
    const longMsg = 'A'.repeat(50);
    render(<ConversationCard conversation={makeConv({ lastMessage: longMsg })} />);
    const el = screen.getByTestId('conv-last-message');
    expect(el.textContent!.length).toBeLessThanOrEqual(41); // 40 + ellipsis
    expect(el.textContent).toContain('…');
  });

  it('TC-15b: short message not truncated', () => {
    render(<ConversationCard conversation={makeConv({ lastMessage: 'Hello' })} />);
    expect(screen.getByTestId('conv-last-message')).toHaveTextContent('Hello');
  });

  it('TC-09 (partial): click triggers onClick', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<ConversationCard conversation={makeConv()} onClick={onClick} />);
    await user.click(screen.getByTestId('conv-card-conv-001'));
    expect(onClick).toHaveBeenCalledWith('conv-001');
  });

  it('displays correct status tag for idle', () => {
    render(<ConversationCard conversation={makeConv({ mode: 'auto', lastMessageSender: '' })} />);
    expect(screen.getByTestId('conv-status-tag')).toHaveTextContent('空闲');
  });

  it('displays correct status tag for human-takeover', () => {
    render(<ConversationCard conversation={makeConv({ mode: 'takeover' })} />);
    expect(screen.getByTestId('conv-status-tag')).toHaveTextContent('人工接管');
  });
});
