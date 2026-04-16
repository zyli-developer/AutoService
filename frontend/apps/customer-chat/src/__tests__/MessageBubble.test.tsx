import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MessageBubble } from '../components/MessageBubble';
import type { ChatMessage } from '../store/chatStore';

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    source: 'customer',
    sourceRole: 'customer',
    content: 'Test message',
    visibility: 'public',
    timestamp: '2026-04-16T09:00:00.000Z',
    sequenceNumber: 1,
    status: 'sent',
    ...overrides,
  };
}

describe('MessageBubble', () => {
  it('TC-011: customer message is right-aligned with blue background', () => {
    const msg = makeMessage({ sourceRole: 'customer', content: 'Hi there' });
    const { container } = render(<MessageBubble message={msg} />);

    // Outer div should have justify-end
    const outer = container.firstChild as HTMLElement;
    expect(outer.className).toContain('justify-end');

    // Inner bubble should have blue background
    const bubble = outer.querySelector('.bg-blue-500');
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toBe('Hi there');
  });

  it('TC-012: sending status shows sending indicator', () => {
    const msg = makeMessage({ status: 'sending', content: 'Sending...' });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId('sending-indicator')).toBeInTheDocument();
  });

  it('TC-013: D1 fallback — sourceRole undefined, source includes "agent" → treated as agent (left-aligned)', () => {
    const msg = makeMessage({
      sourceRole: undefined,
      source: 'agent-bot-1',
      content: 'Agent reply',
    });
    const { container } = render(<MessageBubble message={msg} />);

    const outer = container.firstChild as HTMLElement;
    expect(outer.className).toContain('justify-start');

    // Should have gray background (agent)
    const bubble = outer.querySelector('.bg-slate-100');
    expect(bubble).not.toBeNull();
  });
});
