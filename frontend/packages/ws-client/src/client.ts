import { parseEnvelope, type Envelope } from './envelope';
import type { FeToBeType, BeToFeType, ClientHelloPayload, ServerHelloPayload, ErrorPayload } from './types';
import { ERROR_CODES } from './types';

export interface WSClientOptions {
  url: string;
  clientApp: string;
  protocolVersion?: number;
  heartbeatMs?: number;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
  ackTimeoutMs?: number;
  lastSeen?: string;
  conversationId?: string;
  operatorId?: string;
  squads?: string[];
  onFrame?: (frame: Envelope) => void;
  onOpen?: (hello: ServerHelloPayload) => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (err: unknown) => void;
}

interface PendingAck {
  resolve: () => void;
  reject: (err: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * 原生 WebSocket 客户端骨架 · 遵循 T0.2 v1.0
 * - 自动重连（指数退避）
 * - 心跳 ping/pong（默认 15s）
 * - ack 等待（默认 5s 超时后 reject，由上层决策是否重发）
 *
 * TODO(T1B.4): 断线重连时根据 `last_seen` 发 client_hello 做消息回放
 * TODO(T1B.4): per-subscription cursor 推进（收到 event 后主动 client_ack）
 */
export class WSClient {
  private ws: WebSocket | null = null;
  private closedByUser = false;
  private versionIncompatible = false;
  private handshakeComplete = false;
  private reconnectAttempt = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pendingAcks = new Map<string, PendingAck>();

  constructor(private readonly opts: WSClientOptions) {}

  get connected(): boolean {
    return this.handshakeComplete;
  }

  connect(): void {
    this.closedByUser = false;
    this.versionIncompatible = false;
    this.handshakeComplete = false;
    this.open();
  }

  close(code = 1000, reason = 'client_close'): void {
    this.closedByUser = true;
    this.stopHeartbeat();
    this.ws?.close(code, reason);
  }

  /** 发帧；返回在收到 ack 时 resolve 的 Promise（超时 reject）。 */
  send(type: FeToBeType, payload: unknown): Promise<void> {
    const frame: Envelope = {
      v: 1,
      type,
      id: cryptoRandomId(),
      ts: new Date().toISOString(),
      payload,
    };
    const raw = JSON.stringify(frame);

    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('ws_not_open'));
        return;
      }
      const timeout = this.opts.ackTimeoutMs ?? 5000;
      const timer = setTimeout(() => {
        this.pendingAcks.delete(frame.id);
        reject(new Error(`ack_timeout:${type}`));
      }, timeout);
      this.pendingAcks.set(frame.id, { resolve, reject, timer });
      this.ws.send(raw);
    });
  }

  private open(): void {
    const ws = new WebSocket(this.opts.url);
    this.ws = ws;
    this.handshakeComplete = false;

    ws.addEventListener('open', () => {
      this.reconnectAttempt = 0;
      this.sendClientHello();
    });

    ws.addEventListener('message', (ev) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(typeof ev.data === 'string' ? ev.data : '');
      } catch {
        this.opts.onError?.(new Error('invalid_json'));
        return;
      }
      const result = parseEnvelopeSafe(parsed);
      if (!result.ok) {
        this.opts.onError?.(result.err);
        return;
      }
      const frame = result.frame;

      // Handshake response handling (before general dispatch)
      if (!this.handshakeComplete) {
        if (frame.type === 'server_hello') {
          this.handshakeComplete = true;
          this.startHeartbeat();
          this.opts.onOpen?.(frame.payload as ServerHelloPayload);
          this.opts.onFrame?.(frame);
          return;
        }
        if (frame.type === 'error') {
          const payload = frame.payload as ErrorPayload;
          if (payload.code === ERROR_CODES.VERSION_INCOMPATIBLE) {
            this.versionIncompatible = true;
            this.closedByUser = true; // prevent reconnect
          }
          this.opts.onError?.(payload);
          this.opts.onFrame?.(frame);
          return;
        }
      }

      this.handleAckIfAny(frame);
      this.opts.onFrame?.(frame);
    });

    ws.addEventListener('close', (ev) => {
      this.stopHeartbeat();
      this.handshakeComplete = false;
      this.opts.onClose?.(ev.code, ev.reason);
      this.rejectAllPending(new Error(`ws_closed:${ev.code}`));
      if (!this.closedByUser && !this.versionIncompatible) {
        this.scheduleReconnect();
      }
    });

    ws.addEventListener('error', (err) => {
      this.opts.onError?.(err);
    });
  }

  private sendClientHello(): void {
    const payload: ClientHelloPayload = {
      protocol_version: this.opts.protocolVersion ?? 1,
      client_app: this.opts.clientApp,
    };
    if (this.opts.lastSeen) payload.last_seen = this.opts.lastSeen;
    if (this.opts.conversationId) payload.conversation_id = this.opts.conversationId;
    if (this.opts.operatorId) payload.operator_id = this.opts.operatorId;
    if (this.opts.squads) payload.squads = this.opts.squads;

    const frame: Envelope = {
      v: 1,
      type: 'client_hello' as FeToBeType,
      id: cryptoRandomId(),
      ts: new Date().toISOString(),
      payload,
    };
    this.ws?.send(JSON.stringify(frame));
  }

  private handleAckIfAny(frame: Envelope): void {
    const feTypesWithAck: BeToFeType[] = ['ack', 'error', 'command_response'];
    if (!feTypesWithAck.includes(frame.type as BeToFeType)) return;
    if (!frame.ref) return;
    const pending = this.pendingAcks.get(frame.ref);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingAcks.delete(frame.ref);
    if (frame.type === 'error') {
      pending.reject(frame.payload);
    } else {
      pending.resolve();
    }
  }

  private scheduleReconnect(): void {
    const base = this.opts.reconnectBaseMs ?? 500;
    const max = this.opts.reconnectMaxMs ?? 30_000;
    const delay = Math.min(base * 2 ** this.reconnectAttempt, max);
    this.reconnectAttempt += 1;
    setTimeout(() => {
      if (!this.closedByUser) this.open();
    }, delay);
  }

  private startHeartbeat(): void {
    const interval = this.opts.heartbeatMs ?? 15_000;
    this.heartbeatTimer = setInterval(() => {
      this.send('ping', {}).catch(() => {
        // ack 超时不重要；下次心跳再试，真挂了 close 事件会触发重连
      });
    }, interval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private rejectAllPending(err: unknown): void {
    for (const pending of this.pendingAcks.values()) {
      clearTimeout(pending.timer);
      pending.reject(err);
    }
    this.pendingAcks.clear();
  }
}

function parseEnvelopeSafe(
  raw: unknown,
): { ok: true; frame: Envelope } | { ok: false; err: unknown } {
  try {
    return { ok: true, frame: parseEnvelope(raw) };
  } catch (err) {
    return { ok: false, err };
  }
}

function cryptoRandomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
