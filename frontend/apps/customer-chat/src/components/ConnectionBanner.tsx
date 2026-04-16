import { useTranslation } from '@autoservice/i18n';

interface ConnectionBannerProps {
  status: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

export function ConnectionBanner({ status, isReplaying = false, replayCount = 0 }: ConnectionBannerProps) {
  const { t } = useTranslation();

  if (isReplaying) {
    const replayText = replayCount > 0
      ? t('connection.replaying', { count: replayCount })
      : t('connection.replaying_no_count');
    return (
      <div data-testid="connection-banner" className="web-connection-banner replaying">
        {replayText}
      </div>
    );
  }

  if (status === 'connecting') {
    return (
      <div data-testid="connection-banner" className="web-connection-banner connecting">
        {t('connection.reconnecting')}
      </div>
    );
  }

  if (status === 'closed') {
    return (
      <div data-testid="connection-banner" className="web-connection-banner closed">
        {t('connection.lost')}
      </div>
    );
  }

  return null;
}
