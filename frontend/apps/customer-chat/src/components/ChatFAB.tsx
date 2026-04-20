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
      <div
        className={`web-fab ${highlight ? 'highlight' : ''}`}
        onClick={onClick}
        role="button"
        aria-label={t('customer.chat.open')}
      >
        💬
      </div>
    </>
  );
}
