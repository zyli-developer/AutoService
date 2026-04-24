import { describe, it, expect, beforeEach } from 'vitest';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore, initialState, type Conversation } from '../store/operatorStore';
import { handleEventFrame } from '../hooks/useOperatorWS';

const makeEventFrame = (eventType: string, conversationId: string, data: Record<string, any> = {}): Envelope => ({
  v: 1,
  type: 'event',
  id: crypto.randomUUID(),
  ts: new Date().toISOString(),
  payload: {
    event: {
      id: 'evt-' + Math.random().toString(36).slice(2),
      type: eventType,
      conversation_id: conversationId,
      data,
      timestamp: '2026-04-16T10:00:00Z',
      sequence_number: 1,
    },
  },
} as Envelope);

function dispatch(frame: Envelope) {
  handleEventFrame(
    frame,
    useOperatorStore.getState().addConversation,
    useOperatorStore.getState().updateConversation,
  );
}

function seedConversation(overrides: Partial<Conversation> = {}) {
  const conv: Conversation = {
    id: 'conv-001',
    squadId: 'sq-A',
    customerId: 'cust-001',
    mode: 'auto',
    state: 'created',
    lastMessage: '',
    lastMessageSender: '',
    lastActivityTs: '2026-04-16T09:00:00Z',
    ...overrides,
  };
  useOperatorStore.getState().addConversation(conv);
}

beforeEach(() => {
  useOperatorStore.setState({ ...initialState, conversations: {} });
});

describe('WS event dispatch', () => {
  it('TC-02: conversation.created → new card with status=idle', () => {
    dispatch(makeEventFrame('conversation.created', 'conv-new', {
      squad_id: 'sq-A',
      customer_id: 'cust-alice',
    }));
    const conv = useOperatorStore.getState().conversations['conv-new'];
    expect(conv).toBeDefined();
    expect(conv.squadId).toBe('sq-A');
    expect(conv.customerId).toBe('cust-alice');
    expect(conv.mode).toBe('auto');
    expect(conv.state).toBe('created');
  });

  it('TC-03: mode.changed to=copilot → escalation-pending', () => {
    seedConversation();
    dispatch(makeEventFrame('mode.changed', 'conv-001', { from: 'auto', to: 'copilot' }));
    expect(useOperatorStore.getState().conversations['conv-001'].mode).toBe('copilot');
  });

  it('TC-04: mode.changed to=takeover → human-takeover', () => {
    seedConversation();
    dispatch(makeEventFrame('mode.changed', 'conv-001', { from: 'copilot', to: 'takeover' }));
    expect(useOperatorStore.getState().conversations['conv-001'].mode).toBe('takeover');
  });

  it('TC-05: conversation.closed → state=closed', () => {
    seedConversation();
    dispatch(makeEventFrame('conversation.closed', 'conv-001', {}));
    expect(useOperatorStore.getState().conversations['conv-001'].state).toBe('closed');
  });

  it('TC-06: message.sent sender=customer → waiting-reply', () => {
    seedConversation({ state: 'active' });
    dispatch(makeEventFrame('message.sent', 'conv-001', {
      sender_role: 'customer',
      text: '你好，我需要帮助',
    }));
    const conv = useOperatorStore.getState().conversations['conv-001'];
    expect(conv.lastMessageSender).toBe('customer');
    expect(conv.lastMessage).toBe('你好，我需要帮助');
  });

  it('TC-07: message.sent sender=agent after customer → idle', () => {
    seedConversation({ state: 'active', lastMessageSender: 'customer' });
    dispatch(makeEventFrame('message.sent', 'conv-001', {
      sender_role: 'agent',
      text: '好的，我来帮您处理',
    }));
    const conv = useOperatorStore.getState().conversations['conv-001'];
    expect(conv.lastMessageSender).toBe('agent');
  });

  it('TC-11: conversation.resolved → state=closed', () => {
    seedConversation();
    dispatch(makeEventFrame('conversation.resolved', 'conv-001', {}));
    expect(useOperatorStore.getState().conversations['conv-001'].state).toBe('closed');
  });

  it('own operator_message echo does not duplicate optimistic insert', () => {
    seedConversation({ state: 'active' });
    const convId = 'conv-001';
    const clientId = 'client-uuid-1';
    const serverId = 'server-uuid-1';
    const opId = 'op-42';

    // 1. IMInput-style optimistic insert (client UUID, sender='operator').
    useOperatorStore.getState().addCopilotMessage(convId, {
      id: clientId,
      text: '你好',
      sender: 'operator',
      ts: '2026-04-23T16:31:27.187Z',
      visibility: 'side',
    });

    // 2. EventBus echo of my own send comes back with server id + source=opId.
    handleEventFrame(
      makeEventFrame('message.sent', convId, {
        message_id: serverId,
        source: opId,
        content: '你好',
        visibility: 'side',
      }),
      useOperatorStore.getState().addConversation,
      useOperatorStore.getState().updateConversation,
      useOperatorStore.getState().addCopilotMessage,
      opId,
    );

    const msgs = useOperatorStore.getState().copilotMessages[convId] ?? [];
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe(clientId);
    expect(msgs[0].sender).toBe('operator');
  });

  it('other operator message.sent still inserted when selfOperatorId differs', () => {
    seedConversation({ state: 'active' });
    const convId = 'conv-001';
    handleEventFrame(
      makeEventFrame('message.sent', convId, {
        message_id: 'srv-2',
        source: 'op-other',
        content: '别人发的',
        visibility: 'side',
      }),
      useOperatorStore.getState().addConversation,
      useOperatorStore.getState().updateConversation,
      useOperatorStore.getState().addCopilotMessage,
      'op-42',
    );
    const msgs = useOperatorStore.getState().copilotMessages[convId] ?? [];
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe('srv-2');
  });

  it('TC-13: multiple sequential events accumulate correctly', () => {
    dispatch(makeEventFrame('conversation.created', 'conv-x', {
      squad_id: 'sq-B',
      customer_id: 'cust-bob',
    }));
    dispatch(makeEventFrame('message.sent', 'conv-x', {
      sender_role: 'customer',
      text: 'Hi',
    }));
    dispatch(makeEventFrame('mode.changed', 'conv-x', { from: 'auto', to: 'copilot' }));

    const conv = useOperatorStore.getState().conversations['conv-x'];
    expect(conv.customerId).toBe('cust-bob');
    expect(conv.lastMessage).toBe('Hi');
    expect(conv.mode).toBe('copilot');
    expect(conv.state).toBe('active');
  });
});
