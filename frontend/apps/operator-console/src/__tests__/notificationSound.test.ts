import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useNotificationSound, _setAudioContextImpl } from '../hooks/useNotificationSound';

describe('useNotificationSound', () => {
  let mockStart: ReturnType<typeof vi.fn>;
  let mockStop: ReturnType<typeof vi.fn>;
  let mockConnect: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockStart = vi.fn();
    mockStop = vi.fn();
    mockConnect = vi.fn();

    const MockAudioContext = vi.fn().mockImplementation(() => ({
      currentTime: 0,
      destination: {},
      createOscillator: vi.fn().mockReturnValue({
        type: 'sine',
        frequency: { value: 440 },
        connect: mockConnect,
        start: mockStart,
        stop: mockStop,
      }),
    }));

    _setAudioContextImpl(MockAudioContext as unknown as typeof AudioContext);
  });

  it('TC-01: playSound creates oscillator and calls start', () => {
    const { playSound } = useNotificationSound();
    playSound();
    expect(mockConnect).toHaveBeenCalled();
    expect(mockStart).toHaveBeenCalled();
    expect(mockStop).toHaveBeenCalled();
  });
});
