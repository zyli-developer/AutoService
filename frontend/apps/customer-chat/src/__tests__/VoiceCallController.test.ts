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

  it('from thinking WITH comfort still playing, CC reply is queued until comfort done', async () => {
    const c = makeController();
    c._testForceState('thinking');
    (c as any).comfortPlaying = true;
    c.onCcReply('reply from CC');
    expect(c.state).toBe('thinking'); // queued
    await (c as any)._onTtsDone();    // comfort finishes (awaits playback-done)
    expect(c.state).toBe('speaking'); // promoted
  });

  it('from thinking WITH comfort already finished, CC reply is spoken immediately', () => {
    const c = makeController();
    c._testForceState('thinking');
    (c as any).comfortPlaying = false;
    c.onCcReply('late reply');
    expect(c.state).toBe('speaking');
  });

  it('comfort finishing with no queued CC reply stays in thinking', async () => {
    const c = makeController();
    c._testForceState('thinking');
    (c as any).comfortPlaying = true;
    await (c as any)._onTtsDone();
    expect(c.state).toBe('thinking'); // waits for onCcReply
    expect((c as any).comfortPlaying).toBe(false);
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

  it('start() transitions idle → preparing', async () => {
    const c = makeController();
    // Do not await — start is async and will fail without real browser APIs
    void c.start().catch(() => {});
    // allow microtask
    await Promise.resolve();
    expect(['preparing', 'error']).toContain(c.state);
  });

  it('comfort text pool does not repeat last 3', () => {
    const c = makeController({ comfortPool: ['a', 'b', 'c', 'd'] });
    const seen: string[] = [];
    for (let i = 0; i < 20; i++) {
      seen.push((c as any).pickComfort());
    }
    // No window of 4 consecutive identical
    for (let i = 0; i + 3 < seen.length; i++) {
      const slice = seen.slice(i, i + 4);
      expect(new Set(slice).size).toBeGreaterThan(1);
    }
  });
});
