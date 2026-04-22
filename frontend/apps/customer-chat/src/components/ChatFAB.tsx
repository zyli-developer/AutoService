import { useTranslation } from '@autoservice/i18n';

interface ChatFABProps {
  onClick: () => void;
  onCallClick?: () => void;
  highlight?: boolean;
}

export function ChatFAB({ onClick, onCallClick, highlight = false }: ChatFABProps) {
  const { t } = useTranslation();
  return (
    <>
      <button
        type="button"
        className="web-fab-call"
        onClick={onCallClick}
        aria-label={t('customer.chat.openVoice')}
        disabled={!onCallClick}
        data-testid="voice-fab"
      >
        📞
      </button>
      <button
        type="button"
        className={`web-fab ${highlight ? 'highlight' : ''}`}
        onClick={onClick}
        aria-label={t('customer.chat.open')}
      >
        💬
      </button>
    </>
  );
}
