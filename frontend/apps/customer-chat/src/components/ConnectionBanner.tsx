import { useTranslation } from '@autoservice/i18n';

interface ConnectionBannerProps {
  status: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

export function ConnectionBanner({ status, isReplaying = false, replayCount = 0 }: ConnectionBannerProps) {
  const { t } = useTranslation();

  // Replaying takes priority over connection status
  if (isReplaying) {
    const replayText = replayCount > 0
      ? t('connection.replaying', { count: replayCount })
      : t('connection.replaying_no_count');
    return (
      <div
        data-testid="connection-banner"
        className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-500"
      >
        {replayText}
      </div>
    );
  }

  if (status === 'connecting') {
    return (
      <div
        data-testid="connection-banner"
        className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-500"
      >
        <>
          <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
          {t('connection.reconnecting')}
        </>
      </div>
    );
  }

  if (status === 'closed') {
    return (
      <div
        data-testid="connection-banner"
        className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-500"
      >
        {t('connection.lost')}
      </div>
    );
  }

  return null;
}
