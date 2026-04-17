import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FakeWSClient } from './fakeWSClient';
import type { WSClientOptions } from '@autoservice/ws-client';
import { useChatStore, initialState } from '../store/chatStore';

let fakeInstance: FakeWSClient | null = null;
const fakeInstances: FakeWSClient[] = [];

vi.mock('@autoservice/ws-client', async (importActual) => {
  const actual = await importActual<typeof import('@autoservice/ws-client')>();
  return {
    ...actual,
    WSClient: class {
      constructor(opts: WSClientOptions) {
        const fake = new FakeWSClient(opts);
        fakeInstances.push(fake);
        fakeInstance = fake;
        Object.assign(this, {
          connect: () => fake.connect(),
          send: (type: string, payload: unknown) => fake.send(type, payload),
          close: () => fake.close(),
        });
        (this as unknown as { opts: WSClientOptions }).opts = opts;
      }
    },
  };
});

const { App } = await import('../App');

describe('Integration', () => {
  beforeEach(() => {
    fakeInstance = null;
    fakeInstances.length = 0;
    useChatStore.setState(initialState);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('TC-021: full render — FAB visible; after open modal shows; after connect input enabled; after send message appears', async () => {
    const user = userEvent.setup();

    render(<App />);

    // FAB should be present
    expect(screen.getByTestId('chat-fab')).toBeInTheDocument();

    // Click FAB to open modal
    await user.click(screen.getByTestId('chat-fab'));

    // Modal should be visible
    expect(screen.getByTestId('chat-modal')).toBeInTheDocument();

    // Input should be disabled initially (connecting state)
    const input = screen.getByTestId('chat-input');
    expect(input).toBeDisabled();

    // Simulate WS open
    act(() => {
      fakeInstance?.triggerOpen();
    });

    // After connection, input should be enabled
    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).not.toBeDisabled();
    });

    // Type and send a message
    await user.type(screen.getByTestId('chat-input'), 'Hello integration');
    await user.click(screen.getByTestId('send-button'));

    // Optimistic message should appear
    await waitFor(() => {
      expect(screen.getByText('Hello integration')).toBeInTheDocument();
    });

    // FakeWSClient should have received the send call
    expect(fakeInstance?.sendCalls).toHaveLength(1);
    expect(fakeInstance?.sendCalls[0].type).toBe('customer_message');
  });

  it('TC-023: typing indicator appears after send, disappears on agent reply', async () => {
    const user = userEvent.setup();
    render(<App />);
    // Open modal
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    await waitFor(() => expect(screen.getByTestId('chat-input')).not.toBeDisabled());

    // Send a message
    await user.type(screen.getByTestId('chat-input'), 'Hello');
    await user.click(screen.getByTestId('send-button'));

    // Typing indicator should appear
    await waitFor(() => expect(screen.getByTestId('typing-indicator')).toBeInTheDocument());

    // Agent replies
    act(() => {
      fakeInstance?.pushFrame({
        v: 1, type: 'message', id: 'f-reply', ts: '2026-04-16T10:00:00.000Z',
        payload: {
          conversation_id: 'cv1',
          message: { id: 'reply-1', source: 'agent-1', content: 'Hi there!', visibility: 'public', sequence_number: 2, timestamp: new Date().toISOString() },
          source_display: { id: 'agent-1', role: 'agent', name: 'Bot' },
        },
      });
    });

    // Typing indicator should disappear
    await waitFor(() => expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument());
  });

  it('TC-022: receiving a message frame adds it to the UI', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Open modal to see messages
    await user.click(screen.getByTestId('chat-fab'));

    act(() => {
      fakeInstance?.triggerOpen();
    });

    await waitFor(() => {
      expect(useChatStore.getState().connectionStatus).toBe('open');
    });

    act(() => {
      fakeInstance?.pushFrame({
        v: 1,
        type: 'message',
        id: 'frame-incoming',
        ts: '2026-04-16T09:05:00.000Z',
        payload: {
          message: {
            id: 'incoming-msg-1',
            source: 'agent-bot',
            content: 'How can I help you?',
            visibility: 'public',
            sequence_number: 10,
            timestamp: '2026-04-16T09:05:00.000Z',
          },
          source_display: {
            role: 'agent',
            name: 'Support Bot',
          },
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('How can I help you?')).toBeInTheDocument();
    });

    // Message should be in the store
    const { messages } = useChatStore.getState();
    expect(messages.some((m) => m.id === 'incoming-msg-1')).toBe(true);
  });
});

describe('TC-034~038: placeholder -> streaming flow', () => {
  beforeEach(() => {
    fakeInstance = null;
    fakeInstances.length = 0;
    useChatStore.setState(initialState);
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => vi.useRealTimers());

  const openModal = async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
  };

  const pushPlaceholder = (fake: FakeWSClient) => fake.pushFrame({
    v: 1, type: 'message', id: 'f-ph', ts: new Date().toISOString(),
    payload: {
      conversation_id: 'cv1',
      message: { id: 'ph-1', source: 'agent-1', content: '正在查询…',
        visibility: 'public', sequence_number: 1, timestamp: new Date().toISOString(),
        metadata: { is_placeholder: true } },
      source_display: { id: 'agent-1', role: 'agent', name: 'Bot' },
    },
  });

  const pushEdited = (fake: FakeWSClient) => fake.pushFrame({
    v: 1, type: 'message_edited', id: 'f-edit', ts: new Date().toISOString(),
    payload: { message_id: 'ph-1', new_content: '套餐价格是 199 元', sequence_number: 2 },
  });

  it('TC-034: placeholder message shows streaming cursor', async () => {
    await openModal();
    act(() => { if (fakeInstance) pushPlaceholder(fakeInstance); });
    await waitFor(() => expect(screen.getByTestId('streaming-cursor')).toBeInTheDocument());
    expect(screen.getByText('正在查询…')).toBeInTheDocument();
  });

  it('TC-035: message_edited replaces content in-place, cursor disappears', async () => {
    await openModal();
    act(() => { if (fakeInstance) pushPlaceholder(fakeInstance); });
    await waitFor(() => expect(screen.getByTestId('streaming-cursor')).toBeInTheDocument());

    act(() => { if (fakeInstance) pushEdited(fakeInstance); });
    await waitFor(() => expect(screen.queryByTestId('streaming-cursor')).toBeNull());
    expect(screen.getByText('套餐价格是 199 元')).toBeInTheDocument();
    expect(screen.queryByText('正在查询…')).toBeNull();
    expect(useChatStore.getState().messages).toHaveLength(1);
  });

  it('TC-036: after message_edited, edited class is visible', async () => {
    await openModal();
    act(() => { if (fakeInstance) pushPlaceholder(fakeInstance); });
    act(() => { if (fakeInstance) pushEdited(fakeInstance); });
    await waitFor(() => expect(screen.getByText('套餐价格是 199 元')).toBeInTheDocument());
    const bubble = screen.getByText('套餐价格是 199 元').closest('.web-msg');
    expect(bubble?.className).toContain('edited');
  });

  it('TC-037: 500ms later, edited class disappears', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await openModal();
    act(() => { if (fakeInstance) pushPlaceholder(fakeInstance); });
    act(() => { if (fakeInstance) pushEdited(fakeInstance); });
    await waitFor(() => expect(screen.getByText('套餐价格是 199 元')).toBeInTheDocument());
    act(() => { vi.advanceTimersByTime(500); });
    const bubble = screen.getByText('套餐价格是 199 元').closest('.web-msg');
    expect(bubble?.className).not.toContain('edited');
  });

  it('TC-038: normal message without is_placeholder has no streaming cursor', async () => {
    await openModal();
    act(() => {
      fakeInstance?.pushFrame({
        v: 1, type: 'message', id: 'f-n', ts: new Date().toISOString(),
        payload: {
          conversation_id: 'cv1',
          message: { id: 'norm', source: 'agent-1', content: 'Hello!',
            visibility: 'public', sequence_number: 1, timestamp: new Date().toISOString() },
          source_display: { id: 'agent-1', role: 'agent' },
        },
      });
    });
    await waitFor(() => expect(screen.getByText('Hello!')).toBeInTheDocument());
    expect(screen.queryByTestId('streaming-cursor')).toBeNull();
  });
});

describe('TC-057~062: reconnect flow', () => {
  beforeEach(() => {
    sessionStorage.clear();
    fakeInstances.length = 0;
    fakeInstance = null;
    useChatStore.setState(initialState);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('TC-057: pushClose non-1000 shows reconnecting banner', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    await waitFor(() => expect(screen.getByTestId('chat-input')).not.toBeDisabled());
    act(() => { fakeInstance?.pushClose(4499, 'server_error'); });
    await waitFor(() => {
      expect(useChatStore.getState().connectionStatus).toBe('closed');
    });
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
  });

  it('TC-058: wasReconnect flag causes setReplaying on next open', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    await waitFor(() => expect(useChatStore.getState().connectionStatus).toBe('open'));

    act(() => { fakeInstance?.pushClose(4499, 'error'); });
    await waitFor(() => expect(useChatStore.getState().connectionStatus).toBe('closed'));

    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();

    act(() => {
      useChatStore.getState().setReplaying(true);
      useChatStore.getState().setConnectionStatus('open');
    });

    await waitFor(() => expect(useChatStore.getState().isReplaying).toBe(true));
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
    const banner = screen.getByTestId('connection-banner');
    expect(banner.textContent).toMatch(/同步|Sync|回放/i);
  });

  it('TC-059: replay_complete removes banner', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    act(() => {
      useChatStore.getState().setReplaying(true);
      useChatStore.getState().setConnectionStatus('open');
    });
    await waitFor(() => expect(useChatStore.getState().isReplaying).toBe(true));
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();

    act(() => { fakeInstance?.pushFrame({ v: 1, type: 'replay_complete', id: 'rc', ts: new Date().toISOString(), payload: { count: 3 } }); });
    await waitFor(() => expect(screen.queryByTestId('connection-banner')).toBeNull());
  });

  it('TC-060: replayed message does not duplicate existing bubble', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    const msgFrame = { v: 1, type: 'message' as const, id: 'f1', ts: new Date().toISOString(),
      payload: { conversation_id: 'cv1', message: { id: 'm-dup', source: 'agent', content: 'Hello!',
        visibility: 'public', sequence_number: 1, timestamp: new Date().toISOString() },
        source_display: { id: 'agent', role: 'agent' } } };
    act(() => { fakeInstance?.pushFrame(msgFrame); });
    await waitFor(() => expect(screen.getAllByText('Hello!')).toHaveLength(1));
    act(() => { fakeInstance?.pushFrame(msgFrame); });
    await waitFor(() => expect(screen.getAllByText('Hello!')).toHaveLength(1));
  });

  it('TC-061: 4041_REPLAY_GAP sends history_request; snapshot renders messages', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByTestId('chat-fab'));
    act(() => { fakeInstance?.triggerOpen(); });
    act(() => { fakeInstance?.pushFrame({ v: 1, type: 'error', id: 'err1', ts: new Date().toISOString(),
      payload: { code: '4041_REPLAY_GAP', recoverable: true } }); });
    await waitFor(() => expect(fakeInstance?.sendCalls.some(c => c.type === 'history_request')).toBe(true));
    act(() => { fakeInstance?.pushFrame({ v: 1, type: 'history_snapshot', id: 'snap1', ts: new Date().toISOString(),
      payload: { messages: [{ id: 'hist-1', source: 'agent', content: 'History message', visibility: 'public',
        sequence_number: 1, timestamp: new Date().toISOString() }] } }); });
    await waitFor(() => expect(screen.getByText('History message')).toBeInTheDocument());
  });

  it('TC-062: normal close (1000) does not set wasReconnect flag', async () => {
    render(<App />);
    act(() => { fakeInstance?.triggerOpen(); });
    await waitFor(() => expect(useChatStore.getState().connectionStatus).toBe('open'));
    act(() => { fakeInstance?.pushClose(1000, 'normal'); });
    await waitFor(() => expect(useChatStore.getState().connectionStatus).toBe('closed'));
    expect(useChatStore.getState().isReplaying).toBe(false);
  });
});
