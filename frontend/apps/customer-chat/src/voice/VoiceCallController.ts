// src/voice/VoiceCallController.ts
//
// Backend-driven voice call controller for /ws/voice (E2E session mode by
// default, optionally split). Replaces the previous /asr + /tts adapter
// flow — comfort phrases, multi-bubble FIFO, early-comfort buffering, and
// LLM dispatch all moved to the backend in this protocol. The frontend
// now mostly forwards mic PCM and renders backend state changes.
import { VoiceClient, VoiceServerState, VoiceTranscriptFrame } from './voice-client';
import * as playback from './audio-playback';

export type VoiceState =
  | 'idle' | 'preparing' | 'listening' | 'thinking'
  | 'speaking' | 'ending' | 'error';

export type VoiceErrorReason =
  | 'mic_denied' | 'voice_unreachable' | 'voice_dropped'
  | 'cc_timeout' | 'unknown';

export interface VoiceControllerOptions {
  /** Full ws(s):// URL to /ws/voice (with optional query params). */
  voiceUrl: string;
  /** Backend voice mode. Default 'e2e_session' (Doubao Realtime Dialogue). */
  mode?: 'e2e_session' | 'split';
  /** Optional per-session overrides — backend falls back to GREETING_TEXT
   *  / COMFORT_TEXT / default system_role when absent. */
  greeting?: string;
  comfortText?: string;
  systemRole?: string;
  /** Insert a customer bubble for an ASR final. Bubbles are also written
   *  by the backend, but the optimistic insert keeps the UI snappy. */
  onUserMessage?: (text: string) => void;
  onStateChange?: (s: VoiceState, reason?: string) => void;
}

const _BACKEND_TO_FRONTEND: Record<VoiceServerState, VoiceState | null> = {
  idle: 'idle',
  connecting: 'preparing',
  greeting: 'speaking',
  thinking: 'thinking',
  talking: 'listening',
  ending: 'ending',
};

export class VoiceCallController {
  state: VoiceState = 'idle';
  errorReason: VoiceErrorReason | null = null;
  private client: VoiceClient | null = null;
  private mediaStream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  // Local barge-in: when the user is actively speaking we drop incoming
  // bot TTS bytes instead of enqueueing them. The flag is set by user
  // transcript frames and auto-cleared by a debounce timer so the next
  // bot reply plays normally without any explicit signal from backend.
  private _userSpeaking: boolean = false;
  private _userSpeakingResetTimer: ReturnType<typeof setTimeout> | null = null;
  // Time window (ms) after the last user transcript to keep dropping
  // audio. Long enough to cover natural mid-sentence pauses + the
  // backend's ASR_ENDED → _run_query transition (which flips the
  // server-side suppression flag); short enough that the next bot
  // reply doesn't get unnecessarily clipped.
  private static readonly _BARGE_IN_HOLD_MS = 1500;

  constructor(private opts: VoiceControllerOptions) {}

  async start(): Promise<void> {
    if (this.state !== 'idle' && this.state !== 'error') return;
    this.setState('preparing', 'user_start');

    try {
      // 1. AudioContext + playback player
      this.audioCtx = new AudioContext({ sampleRate: 16000 });
      playback.createPlayer();
      if ((this.state as VoiceState) === 'ending' || (this.state as VoiceState) === 'error') return;

      // 2. Mic permission
      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
      } catch (e) {
        console.debug('[voice] mic_denied', e);
        await this._cleanup();
        this._setError('mic_denied');
        return;
      }
      if ((this.state as VoiceState) === 'ending' || (this.state as VoiceState) === 'error') {
        await this._cleanup();
        return;
      }

      // 3. Connect /ws/voice and send the start frame.
      this.client = new VoiceClient();
      try {
        await this.client.connect(
          this.opts.voiceUrl,
          {
            mode: this.opts.mode ?? 'e2e_session',
            greeting: this.opts.greeting,
            comfortText: this.opts.comfortText,
            systemRole: this.opts.systemRole,
          },
          {
            onState: s => this._onServerState(s),
            onTranscript: f => this._onTranscript(f),
            onAudio: pcm => this._onAudio(pcm),
            onClearAudio: () => {
              // Backend signaled barge-in (ASR_INFO) — same effect as a
              // local user-transcript trigger: drop the queue and start
              // dropping incoming chunks until the debounce timer expires.
              try { playback.clearPlayback(); } catch { /* */ }
              this._userSpeaking = true;
              if (this._userSpeakingResetTimer !== null) {
                clearTimeout(this._userSpeakingResetTimer);
              }
              this._userSpeakingResetTimer = setTimeout(() => {
                this._userSpeaking = false;
                this._userSpeakingResetTimer = null;
              }, VoiceCallController._BARGE_IN_HOLD_MS);
            },
            onTtsResume: () => {
              // Backend signaled a new bot sentence is starting NOW
              // (chat_tts_text / external_rag SENTENCE_START). Release
              // any local barge-in mute immediately so the leading PCM
              // chunks of the new reply are not dropped — without this,
              // a fast bridge.query (< 1.5 s) leaves us in the debounce
              // window and the user hears mid-sentence.
              if (this._userSpeakingResetTimer !== null) {
                clearTimeout(this._userSpeakingResetTimer);
                this._userSpeakingResetTimer = null;
              }
              this._userSpeaking = false;
            },
            onError: msg => {
              console.debug('[voice] server error', msg);
              if (this.state !== 'error') this._setError('voice_dropped');
            },
            onClose: code => {
              if (this.state !== 'ending' && this.state !== 'idle' && this.state !== 'error') {
                console.debug('[voice] ws closed unexpectedly', code);
                this._setError('voice_dropped');
              }
            },
          },
        );
      } catch (e) {
        console.debug('[voice] voice_unreachable', e);
        await this._cleanup();
        this._setError('voice_unreachable');
        return;
      }
      if ((this.state as VoiceState) === 'ending' || (this.state as VoiceState) === 'error') {
        await this._cleanup();
        return;
      }

      // 4. AudioWorklet + wire mic → /ws/voice as PCM.
      await this.audioCtx.audioWorklet.addModule('/pcm-processor.js');
      if ((this.state as VoiceState) === 'ending' || (this.state as VoiceState) === 'error') {
        await this._cleanup();
        return;
      }
      const src = this.audioCtx.createMediaStreamSource(this.mediaStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, 'pcm-processor');
      this.workletNode.port.onmessage = (ev) => {
        const buf = ev.data as ArrayBuffer;
        this.client?.sendAudio(buf);
      };
      src.connect(this.workletNode);

      // No explicit setState here — backend will drive transitions via
      // {type:"state"} frames (connecting → greeting → talking).
    } catch (e) {
      console.debug('[voice] start fail (unknown):', e);
      await this._cleanup();
      this._setError('unknown');
    }
  }

  hangup(): void {
    if (this.state === 'idle' || this.state === 'ending') return;
    this.setState('ending', 'user_hangup');
    try { this.client?.stop(); } catch { /* */ }
    void this._cleanup().then(() => this.setState('idle'));
  }

  retry(): void {
    if (this.state !== 'error') return;
    this.errorReason = null;
    this.setState('preparing', 'retry');
  }

  /** Legacy hook kept for App.tsx compatibility. In /ws/voice mode the
   *  backend speaks bot replies directly via Doubao TTS; the chatStore
   *  push from the customer WS handler is purely for chat history. So
   *  this is a no-op now. */
  onCcReply(_text: string): void { /* no-op in /ws/voice mode */ }

  // ---- test seams ----
  _testForceError(reason: VoiceErrorReason): void { this._setError(reason); }
  _testForceState(s: VoiceState): void { this.setState(s); }
  _testInjectServerState(s: VoiceServerState): void { this._onServerState(s); }
  _testInjectTranscript(f: VoiceTranscriptFrame): void { this._onTranscript(f); }

  private _onServerState(s: VoiceServerState): void {
    const mapped = _BACKEND_TO_FRONTEND[s];
    if (!mapped) return;
    // Don't clobber a frontend-side error/ending mid-flight.
    if (this.state === 'error' || this.state === 'ending') return;
    this.setState(mapped, `server:${s}`);
  }

  private _onTranscript(f: VoiceTranscriptFrame): void {
    if (f.role === 'user' && f.text) {
      // Local barge-in: any user transcript (interim OR final) means
      // the user is producing speech. Drop the in-flight bot playback
      // queue and switch to "muted incoming" mode so subsequent audio
      // chunks (which may still be flowing for the previous bot turn)
      // are dropped on arrival. The reset timer auto-unmutes after
      // _BARGE_IN_HOLD_MS of no further user transcript — long enough
      // to cover natural pauses and the backend's ASR_ENDED → flag-flip
      // window before the next bot reply.
      if (!this._userSpeaking) {
        try { playback.clearPlayback(); } catch { /* */ }
      }
      this._userSpeaking = true;
      if (this._userSpeakingResetTimer !== null) {
        clearTimeout(this._userSpeakingResetTimer);
      }
      this._userSpeakingResetTimer = setTimeout(() => {
        this._userSpeaking = false;
        this._userSpeakingResetTimer = null;
      }, VoiceCallController._BARGE_IN_HOLD_MS);

      // Optimistic right-side bubble on the final transcript.
      if (!f.interim) {
        this.opts.onUserMessage?.(f.text);
      }
    }
    // Bot transcripts arrive as audio anyway; we don't render them as
    // bubbles here because the backend persists agent text via engine
    // and pushes it as a chat message frame (see VoiceSession._persist_agent_text).
  }

  /** Audio chunk from /ws/voice → playback queue, unless barge-in is
   *  active (user currently speaking) in which case we drop the chunk. */
  private _onAudio(pcm: Uint8Array): void {
    if (this._userSpeaking) return;
    playback.enqueue(pcm);
  }

  private setState(s: VoiceState, reason?: string): void {
    this.state = s;
    this.opts.onStateChange?.(s, reason);
    console.debug('[voice]', 'state →', s, reason ?? '');
  }

  private _setError(reason: VoiceErrorReason): void {
    this.errorReason = reason;
    this.setState('error', reason);
  }

  private async _cleanup(): Promise<void> {
    try { this.client?.close(); } catch { /* */ }
    try { this.workletNode?.disconnect(); } catch { /* */ }
    try { this.mediaStream?.getTracks().forEach(t => t.stop()); } catch { /* */ }
    try { playback.closePlayer(); } catch { /* */ }
    try { await this.audioCtx?.close(); } catch { /* */ }
    if (this._userSpeakingResetTimer !== null) {
      clearTimeout(this._userSpeakingResetTimer);
      this._userSpeakingResetTimer = null;
    }
    this._userSpeaking = false;
    this.client = null;
    this.mediaStream = null; this.audioCtx = null; this.workletNode = null;
  }
}
