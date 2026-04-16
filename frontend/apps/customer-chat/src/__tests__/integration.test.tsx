import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FakeWSClient } from './fakeWSClient';
import type { WSClientOptions } from '@autoservice/ws-client';
import { useChatStore, initialState } from '../store/chatStore';

let fakeInstance: FakeWSClient | null = null;

vi.mock('@autoservice/ws-client', async (importActual) => {
  const actual = await importActual<typeof import('@autoservice/ws-client')>();
  return {
    ...actual,
    WSClient: class {
      constructor(opts: WSClientOptions) {
        const fake = new FakeWSClient(opts);
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
    useChatStore.setState(initialState);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('TC-021: full render — header, input visible; after connect input enabled; after send message appears', async () => {
    const user = userEvent.setup();

    render(<App />);

    // Header should be present
    expect(screen.getByTestId('chat-header')).toBeInTheDocument();

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

  it('TC-022: receiving a message frame adds it to the UI', async () => {
    render(<App />);

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
