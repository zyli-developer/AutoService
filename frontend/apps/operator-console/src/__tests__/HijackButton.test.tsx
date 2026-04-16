import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HijackButton } from '../components/HijackButton';
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

describe('HijackButton', () => {
  it('TC-01: renders button with correct label "抢单"', () => {
    const send = vi.fn();
    render(<HijackButton conversationId="conv-001" send={send} />);
    const btn = screen.getByTestId('btn-hijack-conv-001');
    expect(btn).toHaveTextContent(/抢\s*单/);
  });

  it('TC-02: clicking button calls send with correct frame structure', async () => {
    const send = vi.fn();
    const user = userEvent.setup();
    render(<HijackButton conversationId="conv-042" send={send} />);
    await user.click(screen.getByTestId('btn-hijack-conv-042'));
    expect(send).toHaveBeenCalledTimes(1);
    const frame = send.mock.calls[0][0];
    expect(frame.v).toBe(1);
    expect(frame.type).toBe('operator_command');
    expect(frame.payload.command).toBe('/hijack');
    expect(frame.payload.conversation_id).toBe('conv-042');
    expect(frame.id).toBeDefined();
    expect(frame.ts).toBeDefined();
  });

  it('TC-03: disabled prop disables the button', () => {
    const send = vi.fn();
    render(<HijackButton conversationId="conv-001" send={send} disabled />);
    expect(screen.getByTestId('btn-hijack-conv-001')).toBeDisabled();
  });

  it('TC-04: button not shown in ConversationCard when mode=takeover', () => {
    const send = vi.fn();
    render(<ConversationCard conversation={makeConv({ mode: 'takeover' })} send={send} />);
    expect(screen.queryByTestId('btn-hijack-conv-001')).toBeNull();
  });

  it('TC-05: button shown in ConversationCard when mode=auto', () => {
    const send = vi.fn();
    render(<ConversationCard conversation={makeConv({ mode: 'auto' })} send={send} />);
    expect(screen.getByTestId('btn-hijack-conv-001')).toBeInTheDocument();
  });
});
