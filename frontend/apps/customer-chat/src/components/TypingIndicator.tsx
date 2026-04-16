import { useTranslation } from '@autoservice/i18n';

interface TypingIndicatorProps {
  visible: boolean;
}

export function TypingIndicator({ visible }: TypingIndicatorProps) {
  const { t } = useTranslation();

  if (!visible) return null;
  return (
    <div
      data-testid="typing-indicator"
      aria-label={t('typing.indicator')}
      className="web-typing"
    >
      <span />
      <span />
      <span />
    </div>
  );
}
