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
