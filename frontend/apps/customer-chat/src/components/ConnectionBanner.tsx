interface ConnectionBannerProps {
  status: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

export function ConnectionBanner({ status, isReplaying = false, replayCount = 0 }: ConnectionBannerProps) {
  // Replaying takes priority over connection status
  if (isReplaying) {
    return (
      <div
        data-testid="connection-banner"
        className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-500"
      >
        正在同步消息{replayCount > 0 ? ` (${replayCount})` : ''}...
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
          Reconnecting...
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
        Connection lost
      </div>
    );
  }

  return null;
}
