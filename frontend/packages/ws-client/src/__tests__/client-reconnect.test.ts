/**
 * WSClient reconnect policy for fatal handshake errors.
 *
 * The server can reject a connection during the handshake for reasons that
 * will not change on retry (version incompatibility, auth/tenant failures).
 * The client must stop reconnecting in those cases — otherwise it spins in
 * an infinite loop, floods the server, and buries the real error in the
 * console noise (observed 2026-04-22 when /ws/customer?tenant=<unknown>
 * reconnected 145 times before user noticed).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WSClient } from '../client';

type Listener = (ev: unknown) => void;

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  private listeners: Record<string, Listener[]> = {};

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, fn: Listener) {
    (this.listeners[type] ??= []).push(fn);
  }

  removeEventListener() {/* noop */}

  send(raw: string) {
    this.sent.push(raw);
  }

  close(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSED;
    this._emit('close', { code, reason });
  }

  // Test-only helpers
  _emit(type: string, ev: unknown) {
    for (const fn of this.listeners[type] ?? []) fn(ev);
  }

  _open() {
    this.readyState = MockWebSocket.OPEN;
    this._emit('open', {});
  }

  _receive(frame: unknown) {
    this._emit('message', { data: JSON.stringify(frame) });
  }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('WSClient reconnect policy', () => {
  it('stops reconnect on 4011_AUTH during handshake', () => {
    const client = new WSClient({ url: 'ws://test/ws/customer?tenant=bogus', clientApp: 'test' });
    client.connect();

    expect(MockWebSocket.instances).toHaveLength(1);
    const ws = MockWebSocket.instances[0];
    ws._open();

    // Server rejects with auth error then closes
    ws._receive({
      v: 1,
      type: 'error',
      id: 'e1',
      ts: new Date().toISOString(),
      payload: { code: '4011_AUTH', message: 'tenant resolution failed', details: { reason: 'unknown_tenant' } },
    });
    ws.close(1008, 'policy');

    // Advance well past the backoff ceiling; no new socket must appear
    vi.advanceTimersByTime(60_000);

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('reconnects on generic (non-fatal) close', () => {
    const client = new WSClient({
      url: 'ws://test/ws/customer',
      clientApp: 'test',
      reconnectBaseMs: 10,
      reconnectMaxMs: 100,
    });
    client.connect();
    const ws = MockWebSocket.instances[0];
    ws._open();
    // Simulate network blip — no error frame, just close with 1006-ish code
    ws.close(1006, 'network');

    vi.advanceTimersByTime(200);

    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it('still stops reconnect on VERSION_INCOMPATIBLE (regression)', () => {
    const client = new WSClient({ url: 'ws://test/ws/customer', clientApp: 'test' });
    client.connect();
    const ws = MockWebSocket.instances[0];
    ws._open();

    ws._receive({
      v: 1,
      type: 'error',
      id: 'e1',
      ts: new Date().toISOString(),
      payload: { code: '4040_VERSION_INCOMPATIBLE', message: 'upgrade required' },
    });
    ws.close(1002, 'version');

    vi.advanceTimersByTime(60_000);

    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
