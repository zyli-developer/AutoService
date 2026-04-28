// src/voice/voice-client.ts
// Single-WebSocket client for the /ws/voice endpoint (E2E and split modes).
// Replaces the asr-client + tts-client pair used by the legacy /asr+/tts
// adapter mode. Protocol mirrors cc-openclaw/voice_gateway/server.py:
//
// Browser → Server:
//   - first frame: {type:"start", mode:"e2e_session"|"split", greeting?, ...}
//   - audio: binary PCM 16kHz mono
//   - {type:"stop"}
//
// Server → Browser:
//   - {type:"state", state:"connecting"|"greeting"|"talking"|"ending"|"idle"}
//   - {type:"transcript", role:"user"|"bot", text, interim}
//   - {type:"clear_audio"}            (barge-in: drop pending playback)
//   - {type:"error", message}
//   - audio bytes (PCM 24kHz mono from TTS)

export type VoiceServerState =
  | 'idle' | 'connecting' | 'greeting' | 'thinking' | 'talking' | 'ending';

export interface VoiceTranscriptFrame {
  type: 'transcript';
  role: 'user' | 'bot';
  text: string;
  interim: boolean;
}

export interface VoiceStartConfig {
  mode?: 'e2e_session' | 'split';
  greeting?: string;
  comfortText?: string;
  systemRole?: string;
}

export interface VoiceClientHandlers {
  onState: (s: VoiceServerState) => void;
  onTranscript: (f: VoiceTranscriptFrame) => void;
  onAudio: (pcm: Uint8Array) => void;
  onClearAudio: () => void;
  /** Backend signals a new bot utterance is starting (chat_tts_text /
   *  external_rag SENTENCE_START). Frontend should release any local
   *  barge-in mute so the new sentence plays from its first chunk. */
  onTtsResume: () => void;
  onError: (msg: string) => void;
  onClose: (code: number) => void;
}

export class VoiceClient {
  private ws: WebSocket | null = null;

  /** Open the WS, send the start frame, and wire frame handlers. The
   *  promise resolves when the WS open event fires; failures (network,
   *  4xx, etc.) reject. */
  connect(url: string, startConfig: VoiceStartConfig, handlers: VoiceClientHandlers): Promise<void> {
    return new Promise((resolve, reject) => {
      let opened = false;
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      this.ws = ws;

      ws.onopen = () => {
        opened = true;
        try {
          ws.send(JSON.stringify({ type: 'start', ...startConfig }));
        } catch (e) {
          reject(e);
          return;
        }
        resolve();
      };

      let audioChunkCount = 0;
      let audioBytesTotal = 0;
      ws.onmessage = (ev) => {
        if (typeof ev.data === 'string') {
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(ev.data) as Record<string, unknown>;
          } catch {
            return;
          }
          const t = parsed.type;
          // eslint-disable-next-line no-console
          console.debug('[voice-client] frame', t, parsed);
          if (t === 'state' && typeof parsed.state === 'string') {
            handlers.onState(parsed.state as VoiceServerState);
          } else if (t === 'transcript') {
            handlers.onTranscript({
              type: 'transcript',
              role: (parsed.role as 'user' | 'bot') ?? 'bot',
              text: (parsed.text as string) ?? '',
              interim: Boolean(parsed.interim),
            });
          } else if (t === 'clear_audio') {
            handlers.onClearAudio();
          } else if (t === 'tts_resume') {
            handlers.onTtsResume();
          } else if (t === 'error') {
            handlers.onError((parsed.message as string) ?? 'voice error');
          }
        } else if (ev.data instanceof ArrayBuffer) {
          audioChunkCount += 1;
          audioBytesTotal += ev.data.byteLength;
          // eslint-disable-next-line no-console
          console.debug(
            '[voice-client] audio chunk #%d (%d bytes) total=%d',
            audioChunkCount, ev.data.byteLength, audioBytesTotal,
          );
          handlers.onAudio(new Uint8Array(ev.data));
        }
      };

      ws.onerror = () => {
        if (!opened) reject(new Error('voice ws error before open'));
        else handlers.onError('voice ws error');
      };

      ws.onclose = (ev) => {
        if (!opened) {
          reject(new Error(`voice ws closed before open: ${ev.code}`));
          return;
        }
        handlers.onClose(ev.code);
      };
    });
  }

  /** Send raw PCM (16kHz mono int16) for ASR. */
  sendAudio(buf: ArrayBuffer): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(buf);
    } catch {
      /* socket gone */
    }
  }

  /** Graceful stop — backend transitions ending → idle, then closes. */
  stop(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(JSON.stringify({ type: 'stop' }));
    } catch {
      /* socket gone */
    }
  }

  close(): void {
    try { this.ws?.close(); } catch { /* */ }
    this.ws = null;
  }

  /** Test seam: forces an `onmessage` event with the given payload as if
   *  the server sent it. Used by VoiceCallController.test.ts. */
  _testInjectMessage(data: string | ArrayBuffer): void {
    const ws = this.ws;
    if (!ws || !ws.onmessage) return;
    const ev = { data } as MessageEvent;
    ws.onmessage(ev);
  }
}
