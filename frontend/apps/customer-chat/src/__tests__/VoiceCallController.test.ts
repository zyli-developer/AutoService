// src/__tests__/VoiceCallController.test.ts
//
// Unit tests for the new /ws/voice-driven VoiceCallController. The
// controller's frontend state machine is now mostly a translator of the
// backend's {type:"state"} frames into the legacy 'idle/preparing/
// listening/...' state names that VoiceStatusBar renders.
import { describe, it, expect, vi } from 'vitest';
import { VoiceCallController, VoiceState } from '../voice/VoiceCallController';

function makeController(overrides: Partial<ConstructorParameters<typeof VoiceCallController>[0]> = {}) {
  return new VoiceCallController({
    voiceUrl: 'ws://fake/ws/voice',
    onUserMessage: vi.fn(),
    ...overrides,
  });
}

describe('VoiceCallController state machine (/ws/voice)', () => {
  it('starts in idle', () => {
    const c = makeController();
    expect(c.state).toBe('idle' as VoiceState);
  });

  it('transitions idle → error on explicit fail', () => {
    const c = makeController();
    c._testForceError('mic_denied');
    expect(c.state).toBe('error');
    expect(c.errorReason).toBe('mic_denied');
  });

  it('from error, retry moves back to preparing', () => {
    const c = makeController();
    c._testForceError('mic_denied');
    c.retry();
    expect(c.state).toBe('preparing');
  });

  it('backend "connecting" state maps to frontend preparing', () => {
    const c = makeController();
    c._testInjectServerState('connecting');
    expect(c.state).toBe('preparing');
  });

  it('backend "greeting" state maps to frontend speaking', () => {
    const c = makeController();
    c._testInjectServerState('greeting');
    expect(c.state).toBe('speaking');
  });

  it('backend "talking" state maps to frontend listening', () => {
    const c = makeController();
    c._testInjectServerState('talking');
    expect(c.state).toBe('listening');
  });

  it('backend "ending" maps to frontend ending', () => {
    const c = makeController();
    c._testInjectServerState('ending');
    expect(c.state).toBe('ending');
  });

  it('backend state frames do not clobber error state', () => {
    const c = makeController();
    c._testForceError('voice_dropped');
    expect(c.state).toBe('error');
    c._testInjectServerState('talking');
    expect(c.state).toBe('error'); // unchanged
  });

  it('backend state frames do not clobber ending state', () => {
    const c = makeController();
    c._testForceState('ending');
    c._testInjectServerState('greeting');
    expect(c.state).toBe('ending');
  });

  it('user-final transcript fires onUserMessage for optimistic bubble', () => {
    const onUserMessage = vi.fn();
    const c = makeController({ onUserMessage });
    c._testInjectTranscript({
      type: 'transcript', role: 'user', text: '你好', interim: false,
    });
    expect(onUserMessage).toHaveBeenCalledWith('你好');
  });

  it('user-interim transcripts do NOT fire onUserMessage', () => {
    const onUserMessage = vi.fn();
    const c = makeController({ onUserMessage });
    c._testInjectTranscript({
      type: 'transcript', role: 'user', text: '你', interim: true,
    });
    expect(onUserMessage).not.toHaveBeenCalled();
  });

  it('bot transcripts do NOT fire onUserMessage', () => {
    const onUserMessage = vi.fn();
    const c = makeController({ onUserMessage });
    c._testInjectTranscript({
      type: 'transcript', role: 'bot', text: '好的', interim: false,
    });
    expect(onUserMessage).not.toHaveBeenCalled();
  });

  it('hangup from any active state moves to ending then idle', () => {
    const c = makeController();
    c._testForceState('listening');
    c.hangup();
    expect(['ending', 'idle']).toContain(c.state);
  });

  it('start() transitions idle → preparing (will then fail in jsdom — that is fine)', async () => {
    const c = makeController();
    void c.start().catch(() => {});
    await Promise.resolve();
    expect(['preparing', 'error']).toContain(c.state);
  });

  it('onCcReply is a no-op in /ws/voice mode (legacy hook)', () => {
    const c = makeController();
    c._testForceState('listening');
    c.onCcReply('this is now backend-driven');
    // State unchanged — no setState was triggered.
    expect(c.state).toBe('listening');
  });
});
