// src/voice/useVoiceCall.ts
import { useEffect, useRef, useState } from 'react';
import { VoiceCallController, VoiceState, VoiceErrorReason } from './VoiceCallController';

export interface UseVoiceCallOpts {
  asrUrl: string;
  ttsUrl: string;
  comfortPool: string[];
  onUserMessage: (text: string) => void;
  onSendTextToChat: (text: string) => void;
}

export function useVoiceCall(opts: UseVoiceCallOpts) {
  const [state, setState] = useState<VoiceState>('idle');
  const [errorReason, setErrorReason] = useState<VoiceErrorReason | null>(null);
  const controllerRef = useRef<VoiceCallController | null>(null);

  useEffect(() => {
    const controller = new VoiceCallController({
      ...opts,
      onStateChange: (s) => {
        setState(s);
        if (s === 'error') setErrorReason(controllerRef.current?.errorReason ?? null);
        else setErrorReason(null);
      },
    });
    controllerRef.current = controller;
    return () => {
      controller.hangup();
      controllerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.asrUrl, opts.ttsUrl]);

  // visibilitychange → auto hangup
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'hidden') controllerRef.current?.hangup();
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

  return {
    state,
    errorReason,
    start: () => controllerRef.current?.start(),
    hangup: () => controllerRef.current?.hangup(),
    skip: () => controllerRef.current?.skip(),
    retry: () => controllerRef.current?.retry(),
    onCcReply: (t: string) => controllerRef.current?.onCcReply(t),
  };
}
