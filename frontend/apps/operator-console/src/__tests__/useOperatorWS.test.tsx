import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, act, screen } from '@testing-library/react';
import { useOperatorStore, initialState } from '../store/operatorStore';
import { useOperatorWS, _setWSClientImpl } from '../hooks/useOperatorWS';
import { createFakeWSClientClass, fakeInstance } from './fakeWSClient';

function TestComponent() {
  useOperatorWS('ws://test/ws/operator');
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  return <div data-testid="status">{wsStatus}</div>;
}

beforeEach(() => {
  useOperatorStore.setState(initialState);
  _setWSClientImpl(createFakeWSClientClass() as any);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useOperatorWS', () => {
  it('TC-010: when not logged in, no WS connection is made', () => {
    render(<TestComponent />);
    expect(fakeInstance).toBeNull();
  });

  it('TC-011: after login, wsStatus becomes connecting then open after triggerOpen', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(<TestComponent />);
    expect(screen.getByTestId('status').textContent).toBe('connecting');
    await act(async () => {
      fakeInstance!.triggerOpen();
    });
    expect(screen.getByTestId('status').textContent).toBe('open');
    expect(useOperatorStore.getState().sessionId).toBe('test-op-session');
  });

  it('TC-012: after open, subscribe frames sent for each squad', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    useOperatorStore.getState().addSquad('sq-A');
    useOperatorStore.getState().addSquad('sq-B');
    render(<TestComponent />);
    await act(async () => {
      fakeInstance!.triggerOpen();
    });
    const subscribeCalls = fakeInstance!.sendCalls.filter((f) => f.type === 'subscribe');
    const squadIds = subscribeCalls.map((f) => (f.payload as any).scope.squad_id);
    expect(squadIds).toContain('sq-A');
    expect(squadIds).toContain('sq-B');
  });

  it('TC-013: S13 subscription_added updates store subscriptions', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    useOperatorStore.getState().addSquad('sq-A');
    render(<TestComponent />);
    await act(async () => {
      fakeInstance!.triggerOpen();
    });
    await act(async () => {
      fakeInstance!.pushFrame({
        type: 'subscription_added',
        payload: { subscription_id: 'sub-001', scope: { squad_id: 'sq-A' } },
      });
    });
    expect(useOperatorStore.getState().subscriptions['sq-A']).toBe('sub-001');
  });

  it('TC-014: WS close sets wsStatus to closed', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(<TestComponent />);
    await act(async () => { fakeInstance!.triggerOpen(); });
    await act(async () => { fakeInstance!.pushClose(1001); });
    expect(useOperatorStore.getState().wsStatus).toBe('closed');
  });

  it('TC-015: logout closes WS connection', async () => {
    useOperatorStore.getState().login('op-001', 'tok');
    render(<TestComponent />);
    await act(async () => { fakeInstance!.triggerOpen(); });
    act(() => { useOperatorStore.getState().logout(); });
    // After logout, isLoggedIn=false triggers effect cleanup → client.close()
    expect(fakeInstance!.closeCalled).toBe(true);
  });

  it('TC-016: receiving takeover_warning frame calls setTakeoverWarning', async () => {
    useOperatorStore.getState().login('op42', 'tok');
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active', lastMessage: '', lastMessageSender: '', lastActivityTs: '',
    } as any);

    render(<TestComponent />);
    await act(async () => { fakeInstance!.triggerOpen(); });

    await act(async () => {
      fakeInstance!.pushFrame({
        v: 1, type: 'takeover_warning', id: 'f1', ts: 't',
        payload: { conversation_id: 'c1', remaining_ms: 5000, reason: 'idle' },
      });
    });

    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv?.takeoverWarning?.remainingMs).toBe(5000);
    expect(conv?.takeoverWarning?.warningFrameId).toBe('f1');
  });

  it('TC-017: receiving takeover_warning_cancelled clears takeoverWarning', async () => {
    useOperatorStore.getState().login('op42', 'tok');
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active', lastMessage: '', lastMessageSender: '', lastActivityTs: '',
    } as any);
    useOperatorStore.getState().setTakeoverWarning('c1', {
      remainingMs: 5000, reason: 'idle', warningFrameId: 'f1', armedAt: '2026-04-17T00:00:00Z',
    });

    render(<TestComponent />);
    await act(async () => { fakeInstance!.triggerOpen(); });

    await act(async () => {
      fakeInstance!.pushFrame({
        v: 1, type: 'takeover_warning_cancelled', id: 'f2', ts: 't',
        payload: { conversation_id: 'c1' },
      });
    });

    expect(useOperatorStore.getState().conversations['c1']?.takeoverWarning).toBeUndefined();
  });

  it('TC-018: mode.changed event with takeover_operator_id updates takeoverOperatorId', async () => {
    useOperatorStore.getState().login('op42', 'tok');
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'auto', state: 'active', lastMessage: '', lastMessageSender: '', lastActivityTs: '',
    } as any);

    render(<TestComponent />);
    await act(async () => { fakeInstance!.triggerOpen(); });

    await act(async () => {
      fakeInstance!.pushFrame({
        v: 1, type: 'event', id: 'e1', ts: 't',
        payload: { event: {
          id: 'ev1', type: 'mode.changed', conversation_id: 'c1',
          data: { old_mode: 'auto', new_mode: 'takeover', takeover_operator_id: 'op42' },
          timestamp: 't',
        }},
      });
    });

    const conv = useOperatorStore.getState().conversations['c1'];
    expect(conv?.mode).toBe('takeover');
    expect(conv?.takeoverOperatorId).toBe('op42');
  });
});
