// src/voice/asr-client.ts
export type AsrFrame =
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'speech_started' }
  | { type: 'error'; message: string };

export function parseAsrFrame(raw: string): AsrFrame | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object') return null;
  const t = (data as { type?: unknown }).type;
  if (t === 'partial' || t === 'final') {
    const text = (data as { text?: unknown }).text;
    return typeof text === 'string' ? { type: t, text } : null;
  }
  if (t === 'speech_started') return { type: 'speech_started' };
  if (t === 'error') {
    const message = (data as { message?: unknown }).message;
    return { type: 'error', message: typeof message === 'string' ? message : '' };
  }
  return null;
}

export interface AsrClientEvents {
  onFrame: (frame: AsrFrame) => void;
  onClose: (reason: string) => void;
  onError: (err: string) => void;
}

export class AsrClient {
  private ws: WebSocket | null = null;

  async connect(url: string): Promise<void> {
    this.ws = new WebSocket(url);
    await new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error('no ws'));
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error('asr ws connect failed'));
    });
    this.ws.send(JSON.stringify({ type: 'start' }));
  }

  listen(events: AsrClientEvents): void {
    if (!this.ws) throw new Error('not connected');
    this.ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      const frame = parseAsrFrame(ev.data);
      if (frame) events.onFrame(frame);
    };
    this.ws.onclose = () => events.onClose('closed');
    this.ws.onerror = () => events.onError('ws error');
  }

  sendAudio(pcm: ArrayBuffer): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(pcm);
    }
  }

  async close(): Promise<void> {
    if (this.ws) {
      try {
        this.ws.send(JSON.stringify({ type: 'stop' }));
      } catch { /* already closed */ }
      this.ws.close();
      this.ws = null;
    }
  }
}
