import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MessageBubble } from '../components/MessageBubble';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore, initialState } from '../store/chatStore';

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
  it('TC-011: customer message has web-msg customer class', () => {
    const msg = makeMessage({ sourceRole: 'customer', content: 'Hi there' });
    const { container } = render(<MessageBubble message={msg} />);
    const bubble = container.querySelector('.web-msg.customer');
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toContain('Hi there');
  });

  it('TC-012: sending status shows sending indicator', () => {
    const msg = makeMessage({ status: 'sending', content: 'Sending...' });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId('sending-indicator')).toBeInTheDocument();
  });

  it('TC-013: D1 fallback -- sourceRole undefined, source includes "agent" -> treated as agent', () => {
    const msg = makeMessage({
      sourceRole: undefined,
      source: 'agent-bot-1',
      content: 'Agent reply',
    });
    const { container } = render(<MessageBubble message={msg} />);
    const bubble = container.querySelector('.web-msg.agent');
    expect(bubble).not.toBeNull();
  });

  it('TC-014: image message renders img element when metadata.attachment_url is set', () => {
    const msg = makeMessage({
      content: '',
      metadata: { attachment_url: 'https://example.com/image.png' },
    });
    render(<MessageBubble message={msg} />);
    const img = screen.getByTestId('image-attachment');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', 'https://example.com/image.png');
  });

  it('TC-015: image error shows error placeholder instead of img', () => {
    const msg = makeMessage({
      content: '',
      metadata: { attachment_url: 'https://example.com/broken.png' },
    });
    render(<MessageBubble message={msg} />);
    const img = screen.getByTestId('image-attachment');
    fireEvent.error(img);
    expect(screen.queryByTestId('image-attachment')).not.toBeInTheDocument();
    expect(screen.getByTestId('image-error-placeholder')).toBeInTheDocument();
  });
});

describe('TC-027~030: streaming / justEdited states', () => {
  afterEach(() => {
    vi.useRealTimers();
    useChatStore.setState(initialState);
  });

  it('TC-027: isStreaming=true renders streaming-cursor', () => {
    render(<MessageBubble message={{ id: 'm1', source: 'agent-1', sourceRole: 'agent',
      content: '\u2026', visibility: 'public', timestamp: new Date().toISOString(),
      sequenceNumber: 1, status: 'sent', isStreaming: true }} />);
    expect(screen.getByTestId('streaming-cursor')).toBeInTheDocument();
  });

  it('TC-028: isStreaming=false does not render streaming-cursor', () => {
    render(<MessageBubble message={{ id: 'm2', source: 'agent-1', sourceRole: 'agent',
      content: 'hello', visibility: 'public', timestamp: new Date().toISOString(),
      sequenceNumber: 1, status: 'sent', isStreaming: false }} />);
    expect(screen.queryByTestId('streaming-cursor')).toBeNull();
  });

  it('TC-029: justEdited=true adds edited class', () => {
    render(<MessageBubble message={{ id: 'm3', source: 'agent-1', sourceRole: 'agent',
      content: 'edited', visibility: 'public', timestamp: new Date().toISOString(),
      sequenceNumber: 1, status: 'sent', justEdited: true }} />);
    const bubble = screen.getByText('edited').closest('.web-msg');
    expect(bubble?.className).toContain('edited');
  });

  it('TC-030: justEdited=true triggers clearJustEdited after 500ms', () => {
    vi.useFakeTimers();
    useChatStore.getState().addMessage({
      id: 'm4', source: 'agent-1', sourceRole: 'agent',
      content: 'edited', visibility: 'public',
      timestamp: new Date().toISOString(), sequenceNumber: 1,
      status: 'sent', justEdited: true,
    });
    const msg = useChatStore.getState().messages[0];
    render(<MessageBubble message={msg} />);
    expect(useChatStore.getState().messages[0].justEdited).toBe(true);
    act(() => { vi.advanceTimersByTime(500); });
    expect(useChatStore.getState().messages[0].justEdited).toBe(false);
  });
});
