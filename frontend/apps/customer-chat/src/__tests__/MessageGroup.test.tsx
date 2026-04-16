import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { groupMessages } from '../components/MessageGroup';
import { MessageList } from '../components/MessageList';
import type { ChatMessage } from '../store/chatStore';

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

function makeMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: crypto.randomUUID(),
    source: 'agent-1',
    sourceRole: 'agent',
    content: 'test',
    visibility: 'public',
    timestamp: new Date().toISOString(),
    sequenceNumber: 1,
    status: 'sent',
    ...overrides,
  };
}

describe('groupMessages', () => {
  it('TC-009: same source within 5 min are grouped together', () => {
    const t1 = new Date('2026-04-16T10:00:00Z').toISOString();
    const t2 = new Date('2026-04-16T10:03:00Z').toISOString(); // 3 min later

    const msgs = [
      makeMsg({ id: 'a', source: 'agent-1', timestamp: t1 }),
      makeMsg({ id: 'b', source: 'agent-1', timestamp: t2 }),
    ];

    const groups = groupMessages(msgs);
    expect(groups).toHaveLength(1);
    expect(groups[0].messages).toHaveLength(2);
  });

  it('TC-010: different sources always create separate groups', () => {
    const t1 = new Date('2026-04-16T10:00:00Z').toISOString();
    const t2 = new Date('2026-04-16T10:01:00Z').toISOString();

    const msgs = [
      makeMsg({ id: 'a', source: 'agent-1', timestamp: t1 }),
      makeMsg({ id: 'b', source: 'customer-1', sourceRole: 'customer', timestamp: t2 }),
    ];

    const groups = groupMessages(msgs);
    expect(groups).toHaveLength(2);
  });

  it('TC-011: same source but >5 min gap creates separate groups', () => {
    const t1 = new Date('2026-04-16T10:00:00Z').toISOString();
    const t2 = new Date('2026-04-16T10:06:00Z').toISOString(); // 6 min later

    const msgs = [
      makeMsg({ id: 'a', source: 'agent-1', timestamp: t1 }),
      makeMsg({ id: 'b', source: 'agent-1', timestamp: t2 }),
    ];

    const groups = groupMessages(msgs);
    expect(groups).toHaveLength(2);
  });
});

describe('MessageGroup rendering', () => {
  it('TC-012: customer messages do NOT show sender-avatar', () => {
    const msgs = [
      makeMsg({
        id: 'c1',
        source: 'customer-1',
        sourceRole: 'customer',
        content: 'Hello from customer',
        senderName: 'Alice',
      }),
    ];

    render(<MessageList messages={msgs} />);
    expect(screen.queryByTestId('sender-avatar')).not.toBeInTheDocument();
  });

  it('TC-013: agent messages show sender-avatar', () => {
    const msgs = [
      makeMsg({
        id: 'a1',
        source: 'agent-1',
        sourceRole: 'agent',
        content: 'Hello from agent',
        senderName: 'Bot',
      }),
    ];

    render(<MessageList messages={msgs} />);
    expect(screen.getByTestId('sender-avatar')).toBeInTheDocument();
  });
});
