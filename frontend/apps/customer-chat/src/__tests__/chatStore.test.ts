import { describe, it, expect, beforeEach } from 'vitest';
import { useChatStore, initialState } from '../store/chatStore';
import type { ChatMessage } from '../store/chatStore';

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    source: 'customer',
    sourceRole: 'customer',
    content: 'Hello',
    visibility: 'public',
    timestamp: '2026-04-16T09:00:00.000Z',
    sequenceNumber: 1,
    status: 'sent',
    ...overrides,
  };
}

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState(initialState);
  });

  it('TC-001: initial state has correct defaults', () => {
    const state = useChatStore.getState();
    expect(state.connectionStatus).toBe('idle');
    expect(state.sessionId).toBeNull();
    expect(state.conversationId).toBeNull();
    expect(state.messages).toEqual([]);
  });

  it('TC-002: addMessage appends a message to the list', () => {
    const msg = makeMessage({ id: 'msg-1', content: 'Hello' });
    useChatStore.getState().addMessage(msg);
    const { messages } = useChatStore.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe('msg-1');
    expect(messages[0].content).toBe('Hello');
  });

  it('TC-003: updateMessage changes the content of an existing message', () => {
    const msg = makeMessage({ id: 'msg-2', content: 'Original' });
    useChatStore.getState().addMessage(msg);
    useChatStore.getState().updateMessage('msg-2', 'Updated content');
    const { messages } = useChatStore.getState();
    expect(messages[0].content).toBe('Updated content');
  });

  it('TC-004: confirmOptimistic replaces sending message with server data', () => {
    const clientMsgId = 'client-uuid-1';
    const optimistic = makeMessage({
      id: clientMsgId,
      clientMsgId,
      source: 'customer',
      status: 'sending',
      content: 'Sending...',
    });
    useChatStore.getState().addMessage(optimistic);

    useChatStore.getState().confirmOptimistic(clientMsgId, {
      id: 'server-msg-id-1',
      sequenceNumber: 42,
    });

    const { messages } = useChatStore.getState();
    expect(messages[0].status).toBe('sent');
    expect(messages[0].id).toBe('server-msg-id-1');
    expect(messages[0].sequenceNumber).toBe(42);
  });

  it('TC-005: setConnectionStatus, setSessionId, setConversationId update state', () => {
    useChatStore.getState().setConnectionStatus('open');
    useChatStore.getState().setSessionId('session-abc');
    useChatStore.getState().setConversationId('conv-xyz');

    const state = useChatStore.getState();
    expect(state.connectionStatus).toBe('open');
    expect(state.sessionId).toBe('session-abc');
    expect(state.conversationId).toBe('conv-xyz');
  });

  it('TC-019: setAgentTyping(true) sets isAgentTyping to true', () => {
    useChatStore.getState().setAgentTyping(true);
    expect(useChatStore.getState().isAgentTyping).toBe(true);
  });

  it('TC-020: addMessage with sourceRole=agent clears isAgentTyping', () => {
    useChatStore.getState().setAgentTyping(true);
    expect(useChatStore.getState().isAgentTyping).toBe(true);

    const msg = makeMessage({ id: 'agent-reply', sourceRole: 'agent' });
    useChatStore.getState().addMessage(msg);

    expect(useChatStore.getState().isAgentTyping).toBe(false);
  });

  it('TC-023: updateMessage clears isStreaming and sets justEdited', () => {
    useChatStore.getState().addMessage({
      id: 'm-stream', source: 'agent-1', sourceRole: 'agent',
      content: '占位中…', visibility: 'public',
      timestamp: new Date().toISOString(), sequenceNumber: 1,
      status: 'sent', isStreaming: true,
    });
    useChatStore.getState().updateMessage('m-stream', '真实内容');
    const msg = useChatStore.getState().messages[0];
    expect(msg.content).toBe('真实内容');
    expect(msg.isStreaming).toBe(false);
    expect(msg.justEdited).toBe(true);
  });

  it('TC-024: clearJustEdited sets justEdited to false', () => {
    useChatStore.getState().addMessage({
      id: 'm-edited', source: 'agent-1', sourceRole: 'agent',
      content: 'done', visibility: 'public',
      timestamp: new Date().toISOString(), sequenceNumber: 2,
      status: 'sent', justEdited: true,
    });
    useChatStore.getState().clearJustEdited('m-edited');
    expect(useChatStore.getState().messages[0].justEdited).toBe(false);
  });

  it('TC-025: clearJustEdited only affects target message', () => {
    const base = { source:'agent-1', sourceRole:'agent' as const, content:'x',
      visibility:'public' as const, timestamp: new Date().toISOString(),
      sequenceNumber:1, status:'sent' as const, justEdited: true };
    useChatStore.getState().addMessage({ id: 'ma', ...base });
    useChatStore.getState().addMessage({ id: 'mb', ...base });
    useChatStore.getState().clearJustEdited('ma');
    const msgs = useChatStore.getState().messages;
    expect(msgs.find(m => m.id === 'ma')?.justEdited).toBe(false);
    expect(msgs.find(m => m.id === 'mb')?.justEdited).toBe(true);
  });

  it('TC-026: addMessage with isStreaming=true stores correctly', () => {
    useChatStore.getState().addMessage({
      id: 'ph1', source: 'agent-1', sourceRole: 'agent',
      content: '…', visibility: 'public',
      timestamp: new Date().toISOString(), sequenceNumber: 1,
      status: 'sent', isStreaming: true,
    });
    expect(useChatStore.getState().messages[0].isStreaming).toBe(true);
  });
});
