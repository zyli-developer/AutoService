import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import {
  buildVoiceIframeUrl,
  isVoiceMessage,
  type VoiceCallState,
  type VoiceIframeOpts,
  type VoicePostMessage,
} from '../lib/voice-iframe';

type CallContext = Omit<VoiceIframeOpts, 'baseUrl' | 'call_id'>;

interface VoiceCallModalProps {
  open: boolean;
  onClose: () => void;
  ctx: CallContext;
  baseUrl?: string;
}

type ErrorInfo = { code: string; message: string } | null;

const DEFAULT_VOICE_URL = 'https://voice.ezagent.chat';

function resolveVoiceBaseUrl(override?: string): string {
  if (override) return override;
  const envUrl = (import.meta as unknown as { env?: Record<string, string | undefined> }).env
    ?.VITE_VOICE_WEB_URL;
  return envUrl || DEFAULT_VOICE_URL;
}

export function VoiceCallModal({ open, onClose, ctx, baseUrl }: VoiceCallModalProps) {
  const { t } = useTranslation();
  const [callState, setCallState] = useState<VoiceCallState>('idle');
  const [error, setError] = useState<ErrorInfo>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const callIdRef = useRef<string | null>(null);

  if (open && callIdRef.current === null) {
    callIdRef.current = crypto.randomUUID();
  }

  const iframeSrc = useMemo(() => {
    if (!open || callIdRef.current === null) return '';
    return buildVoiceIframeUrl({
      baseUrl: resolveVoiceBaseUrl(baseUrl),
      call_id: callIdRef.current,
      ...ctx,
    });
  }, [open, baseUrl, ctx, retryNonce]);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      if (!isVoiceMessage(event.data)) return;
      const msg = event.data as VoicePostMessage;
      switch (msg.type) {
        case 'as:voice:ready':
          setCallState('connecting');
          setError(null);
          break;
        case 'as:voice:state':
          setCallState(msg.state);
          break;
        case 'as:voice:error':
          setError({ code: msg.code, message: msg.message });
          setCallState('error');
          break;
        case 'as:voice:close':
          onClose();
          break;
        default:
          break;
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener('message', handleMessage);
    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [open, handleMessage]);

  useEffect(() => {
    if (open) return;
    callIdRef.current = null;
    setCallState('idle');
    setError(null);
    setRetryNonce(0);
  }, [open]);

  const handleHangup = useCallback(() => {
    window.postMessage({ type: 'as:voice:hangup' }, '*');
    onClose();
  }, [onClose]);

  const handleRetry = useCallback(() => {
    setError(null);
    setCallState('idle');
    setRetryNonce((n) => n + 1);
  }, []);

  if (!open) return null;

  const errorText = error
    ? error.code === 'NotAllowedError'
      ? t('customer.voice.error.micDenied')
      : t('customer.voice.error.connectFailed')
    : null;

  return (
    <div
      className="web-voice-modal"
      role="dialog"
      aria-label={t('customer.voice.title')}
      data-testid="voice-modal"
    >
      <div className="web-voice-modal__header">
        <span className="web-voice-modal__title">{t('customer.voice.title')}</span>
        <span className="web-voice-modal__state" data-testid="voice-state">
          {t(`customer.voice.state.${callState}`)}
        </span>
        <button
          type="button"
          className="web-voice-modal__hangup"
          onClick={handleHangup}
          aria-label={t('customer.voice.hangup')}
          data-testid="voice-hangup"
        >
          {t('customer.voice.hangup')}
        </button>
      </div>

      {errorText ? (
        <div className="web-voice-modal__error" role="alert" data-testid="voice-error">
          <p>{errorText}</p>
          {error?.code !== 'NotAllowedError' ? (
            <button
              type="button"
              onClick={handleRetry}
              className="web-voice-modal__retry"
              data-testid="voice-retry"
            >
              {t('customer.voice.retry')}
            </button>
          ) : null}
        </div>
      ) : (
        <iframe
          key={retryNonce}
          className="web-voice-modal__iframe"
          src={iframeSrc}
          allow="microphone"
          title={t('customer.voice.title')}
          data-testid="voice-iframe"
        />
      )}
    </div>
  );
}
