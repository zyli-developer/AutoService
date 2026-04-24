import { useTranslation } from '@autoservice/i18n';

interface ChatFABProps {
  onClick: () => void;
  highlight?: boolean;
}

export function ChatFAB({ onClick, highlight = false }: ChatFABProps) {
  const { t } = useTranslation();
  return (
    <>
      <div className="web-fab-call">📞</div>
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
