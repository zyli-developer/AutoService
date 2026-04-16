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

  it('TC-016: showTimestamp=true shows message-timestamp element', () => {
    const msg = makeMessage({
      timestamp: '2026-04-16T09:30:00Z',
    });
    render(<MessageBubble message={msg} showTimestamp={true} />);
    const ts = screen.getByTestId('message-timestamp');
    expect(ts).toBeInTheDocument();
    // Timestamp text should be non-empty
    expect(ts.textContent).not.toBe('');
  });
});

describe('TC-027~030: streaming / justEdited states', () => {
  afterEach(() => {
    vi.useRealTimers();
    useChatStore.setState(initialState);
  });

  it('TC-027: isStreaming=true renders streaming-cursor', () => {
    render(<MessageBubble message={{ id:'m1', source:'agent-1', sourceRole:'agent',
      content:'…', visibility:'public', timestamp:new Date().toISOString(),
      sequenceNumber:1, status:'sent', isStreaming:true }} />);
    expect(screen.getByTestId('streaming-cursor')).toBeInTheDocument();
  });

  it('TC-028: isStreaming=false does not render streaming-cursor', () => {
    render(<MessageBubble message={{ id:'m2', source:'agent-1', sourceRole:'agent',
      content:'hello', visibility:'public', timestamp:new Date().toISOString(),
      sequenceNumber:1, status:'sent', isStreaming:false }} />);
    expect(screen.queryByTestId('streaming-cursor')).toBeNull();
  });

  it('TC-029: justEdited=true adds ring-2 highlight class', () => {
    render(<MessageBubble message={{ id:'m3', source:'agent-1', sourceRole:'agent',
      content:'edited', visibility:'public', timestamp:new Date().toISOString(),
      sequenceNumber:1, status:'sent', justEdited:true }} />);
    // The inner bubble div should have ring-2
    const bubble = screen.getByText('edited').closest('div[class*="rounded-2xl"]');
    expect(bubble).toHaveClass('ring-2');
  });

  it('TC-030: justEdited=true triggers clearJustEdited after 500ms', () => {
    vi.useFakeTimers();
    // Add to store so clearJustEdited can find it
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
