import { useTranslation } from '@autoservice/i18n';
import type { VoiceState, VoiceErrorReason } from './VoiceCallController';

interface Props {
  state: VoiceState;
  errorReason: VoiceErrorReason | null;
  onSkip: () => void;
  onHangup: () => void;
  onRetry: () => void;
}

export function VoiceStatusBar({ state, errorReason, onSkip, onHangup, onRetry }: Props) {
  const { t } = useTranslation();
  if (state === 'idle') return null;

  const isError = state === 'error';
  const textMap: Record<VoiceState, string> = {
    idle: '',
    preparing: t('voice.status.preparing'),
    listening: t('voice.status.listening'),
    thinking: t('voice.status.thinking'),
    speaking: t('voice.status.speaking'),
    ending: t('voice.status.ending'),
    error: errorReason === 'mic_denied'
      ? t('voice.status.mic_denied')
      : errorReason === 'asr_unreachable' || errorReason === 'tts_unreachable'
        ? t('voice.status.service_unreachable')
        : errorReason === 'cc_timeout'
          ? t('voice.status.cc_timeout')
          : t('voice.status.unknown_error'),
  };

  return (
    <div
      data-testid="voice-status-bar"
      className={`voice-status-bar ${isError ? 'is-error' : ''}`}
      role="status"
      aria-live="polite"
    >
      <span className="voice-status-text">{textMap[state]}</span>
      <div className="voice-status-actions">
        {state === 'speaking' && (
          <button type="button" onClick={onSkip} aria-label={t('voice.action.skip')}>
            {t('voice.action.skip')}
          </button>
        )}
        {isError && (
          <button type="button" onClick={onRetry} aria-label={t('voice.action.retry')}>
            {t('voice.action.retry')}
          </button>
        )}
        {state !== 'error' && state !== 'ending' && (
          <button type="button" onClick={onHangup} aria-label={t('voice.action.hangup')}>
            {t('voice.action.hangup')}
          </button>
        )}
      </div>
    </div>
  );
}
