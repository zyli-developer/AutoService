import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
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
        // Return fake as the instance (proxy pattern)
        Object.assign(this, {
          connect: () => fake.connect(),
          send: (type: string, payload: unknown) => fake.send(type, payload),
          close: () => fake.close(),
        });
        // Store opts on this for assertions
        (this as unknown as { opts: WSClientOptions }).opts = opts;
      }
    },
  };
});

// Import after mock to get the mocked version
const { useWebSocket } = await import('../hooks/useWebSocket');

describe('useWebSocket', () => {
  beforeEach(() => {
    fakeInstance = null;
    useChatStore.setState(initialState);
  });

  it('TC-006: on mount sets connectionStatus to connecting, then open after connect', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));

    // Status should be connecting initially
    expect(useChatStore.getState().connectionStatus).toBe('connecting');

    // Connect the fake client (simulates server hello)
    act(() => {
      fakeInstance?.triggerOpen();
    });

    expect(useChatStore.getState().connectionStatus).toBe('open');
    expect(useChatStore.getState().sessionId).toBe('test-session-123');
    expect(result.current.sessionId).toBe('test-session-123');
  });

  it('TC-007: message frame dispatches addMessage to store', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));

    act(() => {
      fakeInstance?.triggerOpen();
    });

    act(() => {
      fakeInstance?.pushFrame({
        v: 1,
        type: 'message',
        id: 'frame-1',
        ts: '2026-04-16T09:00:00.000Z',
        payload: {
          message: {
            id: 'server-msg-1',
            source: 'agent-1',
            content: 'Hello from agent',
            visibility: 'public',
            sequence_number: 1,
            timestamp: '2026-04-16T09:00:00.000Z',
          },
          source_display: {
            role: 'agent',
            name: 'Support Agent',
          },
        },
      });
    });

    const { messages } = useChatStore.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe('server-msg-1');
    expect(messages[0].content).toBe('Hello from agent');
    expect(messages[0].sourceRole).toBe('agent');
    expect(messages[0].status).toBe('sent');
  });

  it('TC-008: message_edited frame calls updateMessage in store', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));

    act(() => {
      fakeInstance?.triggerOpen();
    });

    // First add a message
    useChatStore.getState().addMessage({
      id: 'msg-to-edit',
      source: 'agent',
      sourceRole: 'agent',
      content: 'Original content',
      visibility: 'public',
      timestamp: '2026-04-16T09:00:00.000Z',
      sequenceNumber: 1,
      status: 'sent',
    });

    act(() => {
      fakeInstance?.pushFrame({
        v: 1,
        type: 'message_edited',
        id: 'frame-2',
        ts: '2026-04-16T09:01:00.000Z',
        payload: {
          message_id: 'msg-to-edit',
          new_content: 'Edited content',
        },
      });
    });

    const { messages } = useChatStore.getState();
    expect(messages[0].content).toBe('Edited content');
  });

  it('TC-009: onClose sets connectionStatus to closed', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));

    act(() => {
      fakeInstance?.triggerOpen();
    });

    expect(useChatStore.getState().connectionStatus).toBe('open');

    act(() => {
      fakeInstance?.pushClose(1006, 'abnormal closure');
    });

    expect(useChatStore.getState().connectionStatus).toBe('closed');
  });

  it('TC-010: WSClient is constructed with heartbeatMs of 20000', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));

    expect(fakeInstance).not.toBeNull();
    expect(fakeInstance!.opts.heartbeatMs).toBe(20_000);
  });

  it('TC-031: message_edited frame reads new_content field (bug fix)', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));
    act(() => { fakeInstance?.triggerOpen(); });

    useChatStore.getState().addMessage({
      id: 'orig-1', source: 'agent-1', sourceRole: 'agent',
      content: '占位中…', visibility: 'public',
      timestamp: new Date().toISOString(), sequenceNumber: 1,
      status: 'sent', isStreaming: true,
    });

    act(() => {
      fakeInstance?.pushFrame({
        v:1, type:'message_edited', id:'f-edit', ts:new Date().toISOString(),
        payload: { message_id:'orig-1', new_content:'套餐价格是 199 元', sequence_number:2 },
      });
    });

    expect(useChatStore.getState().messages[0].content).toBe('套餐价格是 199 元');
  });

  it('TC-032: message frame with is_placeholder=true sets isStreaming=true', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));
    act(() => { fakeInstance?.triggerOpen(); });

    act(() => {
      fakeInstance?.pushFrame({
        v:1, type:'message', id:'f-ph', ts:new Date().toISOString(),
        payload: {
          conversation_id:'cv1',
          message: { id:'ph-msg', source:'agent-1', content:'正在查询…',
            visibility:'public', sequence_number:1, timestamp:new Date().toISOString(),
            metadata: { is_placeholder: true } },
          source_display: { id:'agent-1', role:'agent' },
        },
      });
    });

    expect(useChatStore.getState().messages[0].isStreaming).toBe(true);
  });

  it('TC-033: normal message frame sets isStreaming=false by default', async () => {
    renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat'));
    act(() => { fakeInstance?.triggerOpen(); });

    act(() => {
      fakeInstance?.pushFrame({
        v:1, type:'message', id:'f-norm', ts:new Date().toISOString(),
        payload: {
          conversation_id:'cv1',
          message: { id:'norm-msg', source:'agent-1', content:'Hello!',
            visibility:'public', sequence_number:1, timestamp:new Date().toISOString() },
          source_display: { id:'agent-1', role:'agent' },
        },
      });
    });

    const msg = useChatStore.getState().messages[0];
    expect(msg.isStreaming === false || msg.isStreaming === undefined).toBe(true);
  });
});
