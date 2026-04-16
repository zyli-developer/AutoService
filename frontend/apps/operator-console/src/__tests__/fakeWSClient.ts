import { vi } from 'vitest';
import type { Envelope, ServerHelloPayload } from '@autoservice/ws-client';

type OnOpenCb = (hello: ServerHelloPayload) => void;
type OnCloseCb = (code: number, reason: string) => void;
type OnFrameCb = (frame: Envelope) => void;

interface FakeOpts {
  onOpen?: OnOpenCb;
  onClose?: OnCloseCb;
  onFrame?: OnFrameCb;
}

export class FakeWSClient {
  onOpen?: OnOpenCb;
  onClose?: OnCloseCb;
  onFrame?: OnFrameCb;
  sendCalls: Envelope[] = [];
  closeCalled = false;
  connectCallCount = 0;

  constructor(opts: FakeOpts) {
    this.onOpen = opts.onOpen;
    this.onClose = opts.onClose;
    this.onFrame = opts.onFrame;
  }

  connect() {
    this.connectCallCount++;
    // no-op: test calls triggerOpen manually
  }

  send(frame: Envelope) {
    this.sendCalls.push(frame);
  }

  close() {
    this.closeCalled = true;
    this.onClose?.(1000, 'test close');
  }

  triggerOpen(hello?: Partial<ServerHelloPayload>) {
    this.onOpen?.({
      session_id: 'test-op-session',
      protocol_version: 1,
      server_time: new Date().toISOString(),
      viewer_role: 'OPERATOR',
      accepted_subscriptions: [],
      server_capabilities: [],
      ...hello,
    });
  }

  pushFrame(frame: Partial<Envelope>) {
    this.onFrame?.({ v: 1, id: 'f-test', ts: new Date().toISOString(), ...frame } as Envelope);
  }

  pushClose(code = 1001, reason = 'test') {
    this.onClose?.(code, reason);
  }
}

export let fakeInstance: FakeWSClient | null = null;

export function createFakeWSClientClass() {
  fakeInstance = null;
  return class MockWSClient extends FakeWSClient {
    constructor(opts: FakeOpts) {
      super(opts);
      fakeInstance = this;
    }
  };
}
