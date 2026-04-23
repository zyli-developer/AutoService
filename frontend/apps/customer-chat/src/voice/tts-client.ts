// src/voice/tts-client.ts
export type TtsFrame = { type: 'done' } | { type: 'error'; message: string };

export function parseTtsFrame(raw: string): TtsFrame | null {
  let data: unknown;
  try { data = JSON.parse(raw); } catch { return null; }
  if (!data || typeof data !== 'object') return null;
  const t = (data as { type?: unknown }).type;
  if (t === 'done') return { type: 'done' };
  if (t === 'error') {
    const m = (data as { message?: unknown }).message;
    return { type: 'error', message: typeof m === 'string' ? m : '' };
  }
  return null;
}

export interface TtsClientEvents {
  onAudio: (pcm: Uint8Array) => void;
  onDone: () => void;
  onError: (err: string) => void;
  onClose: () => void;
}

export class TtsClient {
  private ws: WebSocket | null = null;

  async connect(url: string, events: TtsClientEvents): Promise<void> {
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';
    await new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error('no ws'));
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error('tts ws connect failed'));
    });
    // Install handlers immediately post-open so gateway's upstream-auth
    // error frames aren't dropped by a racing absence of onmessage.
    this.ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        const frame = parseTtsFrame(ev.data);
        if (frame?.type === 'done') events.onDone();
        else if (frame?.type === 'error') events.onError(frame.message);
      } else if (ev.data instanceof ArrayBuffer) {
        events.onAudio(new Uint8Array(ev.data));
      }
    };
    this.ws.onclose = () => events.onClose();
    this.ws.onerror = () => events.onError('ws error');
  }

  speak(text: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'speak', text }));
    }
  }

  abort(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'abort' }));
    }
  }

  async close(): Promise<void> {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
