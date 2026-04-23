// src/voice/VoiceCallController.ts
import { AsrClient, AsrFrame } from './asr-client';
import { TtsClient } from './tts-client';
import * as playback from './audio-playback';

export type VoiceState =
  | 'idle' | 'preparing' | 'listening' | 'thinking'
  | 'speaking' | 'ending' | 'error';

export type VoiceErrorReason =
  | 'mic_denied' | 'asr_unreachable' | 'tts_unreachable'
  | 'asr_dropped' | 'tts_dropped' | 'cc_timeout' | 'unknown';

export interface VoiceControllerOptions {
  asrUrl: string;
  ttsUrl: string;
  onUserMessage: (text: string) => void;    // insert user bubble into chat
  onSendTextToChat: (text: string) => void; // send via existing /ws/chat
  comfortPool: string[];
  onStateChange?: (s: VoiceState, reason?: string) => void;
}

export class VoiceCallController {
  state: VoiceState = 'idle';
  errorReason: VoiceErrorReason | null = null;
  private recentComfort: string[] = [];
  private asr: AsrClient | null = null;
  private tts: TtsClient | null = null;
  private mediaStream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private pendingCcReply: string | null = null;

  constructor(private opts: VoiceControllerOptions) {}

  async start(): Promise<void> {
    if (this.state !== 'idle' && this.state !== 'error') return;
    this.setState('preparing', 'user_start');

    try {
      // 1. AudioContext (in user gesture — browser unlock)
      this.audioCtx = new AudioContext({ sampleRate: 16000 });
      playback.createPlayer();
      if (this.state !== 'preparing') return; // hangup raced

      // 2. getUserMedia
      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
      } catch {
        await this._cleanup();
        this._setError('mic_denied');
        return;
      }
      if (this.state !== 'preparing') { await this._cleanup(); return; }

      // 3. ASR + TTS connect
      this.asr = new AsrClient();
      this.tts = new TtsClient();
      try {
        await this.asr.connect(this.opts.asrUrl);
      } catch {
        await this._cleanup();
        this._setError('asr_unreachable');
        return;
      }
      if (this.state !== 'preparing') { await this._cleanup(); return; }
      try {
        await this.tts.connect(this.opts.ttsUrl);
      } catch {
        await this._cleanup();
        this._setError('tts_unreachable');
        return;
      }
      if (this.state !== 'preparing') { await this._cleanup(); return; }

      // Wire listeners only after successful connects
      this.asr.listen({
        onFrame: f => this._onAsrFrame(f),
        onClose: () => {
          if (this.state !== 'ending' && this.state !== 'idle' && this.state !== 'error') {
            this._setError('asr_dropped');
          }
        },
        onError: () => {
          if (this.state !== 'error') this._setError('asr_dropped');
        },
      });
      this.tts.listen({
        onAudio: pcm => playback.enqueue(pcm),
        onDone: () => this._onTtsDone(),
        onError: () => {
          if (this.state !== 'error') this._setError('tts_dropped');
        },
        onClose: () => {
          if (this.state !== 'ending' && this.state !== 'idle' && this.state !== 'error') {
            this._setError('tts_dropped');
          }
        },
      });

      // 4. AudioWorklet
      await this.audioCtx.audioWorklet.addModule('/pcm-processor.js');
      if (this.state !== 'preparing') { await this._cleanup(); return; }
      const src = this.audioCtx.createMediaStreamSource(this.mediaStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, 'pcm-processor');
      this.workletNode.port.onmessage = (ev) => {
        const buf = ev.data as ArrayBuffer;
        this.asr?.sendAudio(buf);
      };
      src.connect(this.workletNode);

      this.setState('listening', 'ready');
    } catch {
      await this._cleanup();
      this._setError('unknown');
    }
  }

  private _onTtsDone(): void {
    if (this.state === 'speaking') {
      this.setState('listening', 'tts_done');
    } else if (this.state === 'thinking' && this.pendingCcReply) {
      const text = this.pendingCcReply;
      this.pendingCcReply = null;
      this.setState('speaking', 'cc_reply_after_comfort');
      this.tts?.speak(text);
    }
  }

  private setState(s: VoiceState, reason?: string): void {
    this.state = s;
    this.opts.onStateChange?.(s, reason);
    // eslint-disable-next-line no-console
    console.debug('[voice]', 'state →', s, reason ?? '');
  }

  private _setError(reason: VoiceErrorReason): void {
    this.errorReason = reason;
    this.setState('error', reason);
  }

  skip(): void {
    if (this.state === 'speaking') {
      this.tts?.abort();
      playback.clearPlayback();
      this.setState('listening', 'user_skip');
    }
  }

  hangup(): void {
    if (this.state === 'idle' || this.state === 'ending') return;
    this.setState('ending', 'user_hangup');
    void this._cleanup().then(() => this.setState('idle'));
  }

  retry(): void {
    if (this.state !== 'error') return;
    this.errorReason = null;
    this.setState('preparing', 'retry');
    // start() wires real preparing pipeline in Task C2.
  }

  onCcReply(text: string): void {
    if (this.state === 'thinking') {
      // if comfort still playing, queue it — _onTtsDone will promote
      this.pendingCcReply = text;
    } else if (this.state === 'listening' || this.state === 'speaking') {
      this.setState('speaking', 'cc_reply');
      this.tts?.speak(text);
    }
  }

  private pickComfort(): string {
    const pool = this.opts.comfortPool.filter(c => !this.recentComfort.includes(c));
    const choice = (pool.length > 0 ? pool : this.opts.comfortPool)[
      Math.floor(Math.random() * (pool.length > 0 ? pool.length : this.opts.comfortPool.length))
    ];
    this.recentComfort.push(choice);
    if (this.recentComfort.length > 3) this.recentComfort.shift();
    return choice;
  }

  private async _cleanup(): Promise<void> {
    try { await this.asr?.close(); } catch {}
    try { await this.tts?.close(); } catch {}
    try { this.workletNode?.disconnect(); } catch {}
    try { this.mediaStream?.getTracks().forEach(t => t.stop()); } catch {}
    try { playback.closePlayer(); } catch {}
    this.asr = null; this.tts = null;
    this.mediaStream = null; this.audioCtx = null; this.workletNode = null;
    this.pendingCcReply = null;
  }

  // ---- test-only hooks (exposed for unit tests; keep _setError/_onAsrFrame private) ----
  _testForceError(reason: VoiceErrorReason): void { this._setError(reason); }
  _testForceState(s: VoiceState): void { this.setState(s); }
  _testOnAsrFrame(f: AsrFrame): void { this._onAsrFrame(f); }

  private _onAsrFrame(f: AsrFrame): void {
    if (f.type === 'final' && this.state === 'listening') {
      this.opts.onUserMessage(f.text);
      this.opts.onSendTextToChat(f.text);
      this.setState('thinking', 'asr_final');
      const comfort = this.pickComfort();
      this.tts?.speak(comfort);
    } else if (f.type === 'error') {
      this._setError('asr_dropped');
    }
  }
}
