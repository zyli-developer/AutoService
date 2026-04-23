import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as playback from '../voice/audio-playback';

describe('audio-playback', () => {
  beforeEach(() => {
    // @ts-expect-error mock AudioContext
    global.AudioContext = vi.fn(() => ({
      currentTime: 0,
      destination: {},
      createGain: () => ({ connect: vi.fn(), gain: { setValueAtTime: vi.fn() } }),
      createBuffer: (_ch: number, length: number) => ({
        getChannelData: () => new Float32Array(length),
        duration: length / 24000,
      }),
      createBufferSource: () => ({ buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn() }),
      close: vi.fn(),
    }));
  });

  it('clearPlayback stops all scheduled sources without throwing', () => {
    playback.createPlayer();
    const pcm = new Uint8Array(640);
    playback.enqueue(pcm);
    expect(() => playback.clearPlayback()).not.toThrow();
  });

  it('closePlayer releases the audio context', () => {
    playback.createPlayer();
    expect(() => playback.closePlayer()).not.toThrow();
  });
});
