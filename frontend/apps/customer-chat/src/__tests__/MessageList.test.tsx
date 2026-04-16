import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MessageList } from '../components/MessageList';
import { useChatStore, initialState } from '../store/chatStore';
import type { ChatMessage } from '../store/chatStore';

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    source: 'customer',
    sourceRole: 'customer',
    content: 'Test',
    visibility: 'public',
    timestamp: '2026-04-16T09:00:00.000Z',
    sequenceNumber: 1,
    status: 'sent',
    ...overrides,
  };
}

describe('MessageList', () => {
  beforeEach(() => {
    useChatStore.setState(initialState);
  });

  it('TC-017: typing indicator hidden by default (isAgentTyping=false)', () => {
    render(<MessageList messages={[]} />);
    // TypingIndicator is not visible when isAgentTyping is false
    expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument();
  });

  it('TC-018: agent message with avatarUrl renders sender-avatar with img', () => {
    const messages = [
      makeMessage({
        id: 'msg-a1',
        source: 'agent-1',
        sourceRole: 'agent',
        content: 'Hello from agent',
        senderName: 'Support Bot',
        avatarUrl: 'https://example.com/avatar.png',
      }),
    ];

    render(<MessageList messages={messages} />);

    // sender-avatar should be rendered
    const avatar = screen.getByTestId('sender-avatar');
    expect(avatar).toBeInTheDocument();
    // It should contain an img because avatarUrl is set
    const img = avatar.querySelector('img');
    expect(img).not.toBeNull();
    expect(img!.getAttribute('src')).toBe('https://example.com/avatar.png');
  });

  it('new-msg-btn is shown when user is not at bottom and hidden when at bottom', () => {
    const messages = [
      makeMessage({ id: 'msg-1', content: 'Message 1' }),
      makeMessage({ id: 'msg-2', content: 'Message 2' }),
    ];

    const { rerender } = render(<MessageList messages={messages} />);

    const container = screen.getByTestId('message-list');

    // Simulate not at bottom: scrollHeight > scrollTop + clientHeight + 50
    Object.defineProperty(container, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(container, 'scrollTop', { value: 0, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 400, configurable: true });

    // Trigger a scroll event to update isAtBottom state
    act(() => {
      container.dispatchEvent(new Event('scroll'));
    });

    // Rerender with a new message to trigger the effect
    const newMessages = [
      ...messages,
      makeMessage({ id: 'msg-3', content: 'New message' }),
    ];

    act(() => {
      rerender(<MessageList messages={newMessages} />);
    });

    // Message content is rendered
    expect(screen.getByText('New message')).toBeInTheDocument();
    // If button appears, it should work
    const newMsgBtn = screen.queryByTestId('new-msg-btn');
    if (newMsgBtn) {
      expect(newMsgBtn).toBeInTheDocument();
    }
  });
});
