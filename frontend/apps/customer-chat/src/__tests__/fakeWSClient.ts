import type { WSClientOptions } from '@autoservice/ws-client';

export class FakeWSClient {
  public opts: WSClientOptions;
  public sendCalls: Array<{ type: string; payload: unknown }> = [];

  constructor(opts: WSClientOptions) {
    this.opts = opts;
  }

  /** Called internally by useWebSocket — no-op so status stays 'connecting' until test triggers open */
  connect() {}

  /** Test helper: simulate server hello (triggers onOpen) */
  triggerOpen() {
    this.opts.onOpen?.({
      session_id: 'test-session-123',
      protocol_version: 1,
      server_time: '2026-04-16T09:00:00.000Z',
      viewer_role: 'CUSTOMER',
      accepted_subscriptions: [],
      server_capabilities: ['streaming'],
    });
  }

  send(type: string, payload: unknown): Promise<void> {
    this.sendCalls.push({ type, payload });
    return Promise.resolve();
  }

  close() {}

  pushFrame(frame: Record<string, unknown>) {
    this.opts.onFrame?.(frame as never);
  }

  pushClose(code = 1000, reason = 'test') {
    this.opts.onClose?.(code, reason);
  }
}
