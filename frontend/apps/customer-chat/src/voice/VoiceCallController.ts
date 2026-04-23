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

  constructor(private opts: VoiceControllerOptions) {}

  private setState(s: VoiceState, reason?: string): void {
    this.state = s;
    this.opts.onStateChange?.(s, reason);
    // eslint-disable-next-line no-console
    console.debug('[voice]', 'state →', s, reason ?? '');
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
    if (this.state === 'thinking' || this.state === 'listening') {
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
  }

  // ---- test-only hooks (prefixed with _test, do NOT use in production) ----
  _testForceError(reason: VoiceErrorReason): void {
    this.errorReason = reason;
    this.setState('error', reason);
  }
  _testForceState(s: VoiceState): void { this.setState(s); }
  _testOnAsrFrame(f: AsrFrame): void { this._onAsrFrame(f); }

  private _onAsrFrame(f: AsrFrame): void {
    if (f.type === 'final' && this.state === 'listening') {
      this.opts.onUserMessage(f.text);
      this.opts.onSendTextToChat(f.text);
      this.setState('thinking', 'asr_final');
    } else if (f.type === 'error') {
      this._testForceError('asr_dropped');
    }
  }
}
