// src/__tests__/VoiceCallController.test.ts
import { describe, it, expect, vi } from 'vitest';
import { VoiceCallController, VoiceState } from '../voice/VoiceCallController';

function makeController(overrides: Partial<ConstructorParameters<typeof VoiceCallController>[0]> = {}) {
  return new VoiceCallController({
    asrUrl: 'ws://fake/asr',
    ttsUrl: 'ws://fake/tts',
    onUserMessage: vi.fn(),
    onSendTextToChat: vi.fn(),
    comfortPool: ['hmm'],
    ...overrides,
  });
}

describe('VoiceCallController state machine', () => {
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

  it('from listening, ASR final moves to thinking and calls onUserMessage', () => {
    const onUserMessage = vi.fn();
    const onSend = vi.fn();
    const c2 = makeController({ onUserMessage, onSendTextToChat: onSend });
    c2._testForceState('listening');
    c2._testOnAsrFrame({ type: 'final', text: 'hello' });
    expect(c2.state).toBe('thinking');
    expect(onUserMessage).toHaveBeenCalledWith('hello');
    expect(onSend).toHaveBeenCalledWith('hello');
  });

  it('from thinking, CC reply transitions to speaking', () => {
    const c = makeController();
    c._testForceState('thinking');
    c.onCcReply('reply from CC');
    expect(c.state).toBe('speaking');
  });

  it('from speaking, skip moves back to listening', () => {
    const c = makeController();
    c._testForceState('speaking');
    c.skip();
    expect(c.state).toBe('listening');
  });

  it('hangup from any active state moves to ending then idle', () => {
    const c = makeController();
    c._testForceState('listening');
    c.hangup();
    expect(['ending', 'idle']).toContain(c.state);
  });
});
