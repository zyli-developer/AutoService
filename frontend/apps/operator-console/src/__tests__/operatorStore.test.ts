import { describe, it, expect, beforeEach } from 'vitest';
import { useOperatorStore, initialState } from '../store/operatorStore';

beforeEach(() => {
  useOperatorStore.setState(initialState);
});

describe('operatorStore', () => {
  it('TC-001: initial state is correct', () => {
    const s = useOperatorStore.getState();
    expect(s.isLoggedIn).toBe(false);
    expect(s.operatorId).toBeNull();
    expect(s.token).toBeNull();
    expect(s.wsStatus).toBe('idle');
    expect(s.squads).toEqual([]);
    expect(s.activeSquadId).toBeNull();
    expect(s.subscriptions).toEqual({});
  });

  it('TC-002: login() updates isLoggedIn, operatorId, token', () => {
    useOperatorStore.getState().login('op-001', 'tok-xyz');
    const s = useOperatorStore.getState();
    expect(s.isLoggedIn).toBe(true);
    expect(s.operatorId).toBe('op-001');
    expect(s.token).toBe('tok-xyz');
  });

  it('TC-003: logout() resets isLoggedIn to false', () => {
    useOperatorStore.getState().login('op-001', 'tok');
    useOperatorStore.getState().logout();
    const s = useOperatorStore.getState();
    expect(s.isLoggedIn).toBe(false);
    expect(s.operatorId).toBeNull();
    expect(s.wsStatus).toBe('idle');
  });

  it('TC-004: addSquad is idempotent; setActiveSquad updates activeSquadId', () => {
    const { addSquad, setActiveSquad } = useOperatorStore.getState();
    addSquad('sq-A');
    expect(useOperatorStore.getState().squads).toEqual(['sq-A']);
    addSquad('sq-A'); // duplicate
    expect(useOperatorStore.getState().squads).toEqual(['sq-A']);
    setActiveSquad('sq-A');
    expect(useOperatorStore.getState().activeSquadId).toBe('sq-A');
  });

  it('TC-005: addSubscription updates subscriptions map', () => {
    useOperatorStore.getState().addSubscription('sq-A', 'sub-001');
    expect(useOperatorStore.getState().subscriptions['sq-A']).toBe('sub-001');
  });
});

describe('takeover warning state', () => {
  beforeEach(() => {
    const logout = useOperatorStore.getState().logout;
    if (typeof logout === 'function') logout();
  });

  function addConv(id = 'c1') {
    useOperatorStore.getState().addConversation({
      id,
      squadId: 'web-support',
      customerId: 'cust1',
      mode: 'takeover',
      state: 'active',
      lastMessage: '',
      lastMessageSender: '',
      lastActivityTs: '',
    } as any);
  }

  it('setTakeoverWarning stores per-conversation', () => {
    addConv('c1');
    useOperatorStore.getState().setTakeoverWarning('c1', {
      remainingMs: 5000,
      reason: 'idle',
      warningFrameId: 'f1',
      armedAt: '2026-04-17T00:00:00Z',
    });
    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv?.takeoverWarning?.remainingMs).toBe(5000);
    expect(conv?.takeoverWarning?.warningFrameId).toBe('f1');
  });

  it('clearTakeoverWarning removes the warning', () => {
    addConv('c1');
    useOperatorStore.getState().setTakeoverWarning('c1', {
      remainingMs: 5000,
      reason: 'idle',
      warningFrameId: 'f1',
      armedAt: '',
    });
    useOperatorStore.getState().clearTakeoverWarning('c1');
    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv?.takeoverWarning).toBeUndefined();
  });

  it('setTakeoverWarning is a no-op for unknown conversation', () => {
    useOperatorStore.getState().setTakeoverWarning('nonexistent', {
      remainingMs: 5000,
      reason: 'idle',
      warningFrameId: 'f1',
      armedAt: '',
    });
    expect(useOperatorStore.getState().conversations['nonexistent']).toBeUndefined();
  });
});

describe('setTakeoverArmed', () => {
  beforeEach(() => {
    useOperatorStore.getState().logout();
  });

  function addConv(id = 'c1') {
    useOperatorStore.getState().addConversation({
      id,
      squadId: 'web-support',
      customerId: 'cust1',
      mode: 'takeover',
      state: 'active',
      lastMessage: '',
      lastMessageSender: '',
      lastActivityTs: '',
    } as any);
  }

  it('stores armedAt, idleMs, warningMs on the conversation', () => {
    addConv('c1');
    useOperatorStore.getState().setTakeoverArmed('c1', {
      armedAt: '2026-04-18T00:00:00Z',
      idleMs: 8000,
      warningMs: 3000,
    });
    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv?.takeoverArmedAt).toBe('2026-04-18T00:00:00Z');
    expect(conv?.takeoverIdleMs).toBe(8000);
    expect(conv?.takeoverWarningMs).toBe(3000);
  });

  it('is a no-op for unknown conversation', () => {
    useOperatorStore.getState().setTakeoverArmed('nonexistent', {
      armedAt: '2026-04-18T00:00:00Z',
      idleMs: 8000,
      warningMs: 3000,
    });
    expect(useOperatorStore.getState().conversations['nonexistent']).toBeUndefined();
  });
});
