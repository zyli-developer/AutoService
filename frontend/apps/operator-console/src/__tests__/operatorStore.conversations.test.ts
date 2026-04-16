import { describe, it, expect, beforeEach } from 'vitest';
import { useOperatorStore, initialState, type Conversation, deriveCardStatus } from '../store/operatorStore';

const makeConv = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: 'conv-001',
  squadId: 'sq-A',
  customerId: 'cust-001',
  mode: 'auto',
  state: 'created',
  lastMessage: '',
  lastMessageSender: '',
  lastActivityTs: '2026-04-16T10:00:00Z',
  ...overrides,
});

beforeEach(() => {
  useOperatorStore.setState({ ...initialState, conversations: {} });
});

describe('operatorStore conversations CRUD', () => {
  it('TC-12a: addConversation adds to map', () => {
    const conv = makeConv();
    useOperatorStore.getState().addConversation(conv);
    expect(useOperatorStore.getState().conversations['conv-001']).toEqual(conv);
  });

  it('TC-12b: updateConversation patches existing', () => {
    useOperatorStore.getState().addConversation(makeConv());
    useOperatorStore.getState().updateConversation('conv-001', { mode: 'copilot' });
    expect(useOperatorStore.getState().conversations['conv-001'].mode).toBe('copilot');
  });

  it('TC-12b: updateConversation ignores unknown id', () => {
    useOperatorStore.getState().addConversation(makeConv());
    useOperatorStore.getState().updateConversation('no-such', { mode: 'copilot' });
    expect(useOperatorStore.getState().conversations['conv-001'].mode).toBe('auto');
  });

  it('TC-12c: removeConversation deletes from map', () => {
    useOperatorStore.getState().addConversation(makeConv());
    useOperatorStore.getState().removeConversation('conv-001');
    expect(useOperatorStore.getState().conversations['conv-001']).toBeUndefined();
  });
});

describe('deriveCardStatus', () => {
  it('closed state → closed', () => {
    expect(deriveCardStatus(makeConv({ state: 'closed' }))).toBe('closed');
  });

  it('takeover mode → human-takeover', () => {
    expect(deriveCardStatus(makeConv({ state: 'active', mode: 'takeover' }))).toBe('human-takeover');
  });

  it('copilot mode → escalation-pending', () => {
    expect(deriveCardStatus(makeConv({ state: 'active', mode: 'copilot' }))).toBe('escalation-pending');
  });

  it('customer sent last → waiting-reply', () => {
    expect(deriveCardStatus(makeConv({ state: 'active', mode: 'auto', lastMessageSender: 'customer' }))).toBe('waiting-reply');
  });

  it('default → idle', () => {
    expect(deriveCardStatus(makeConv({ state: 'active', mode: 'auto', lastMessageSender: '' }))).toBe('idle');
  });
});
