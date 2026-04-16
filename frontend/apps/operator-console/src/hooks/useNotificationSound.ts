let AudioContextImpl: typeof AudioContext = globalThis.AudioContext;

/** For testing: inject a mock AudioContext constructor. */
export function _setAudioContextImpl(impl: typeof AudioContext) {
  AudioContextImpl = impl;
}

export function useNotificationSound() {
  const playSound = () => {
    const ctx = new AudioContextImpl();
    const osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.value = 440;
    osc.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.1);
  };

  return { playSound };
}
