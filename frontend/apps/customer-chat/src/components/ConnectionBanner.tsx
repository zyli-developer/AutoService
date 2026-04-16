interface ConnectionBannerProps {
  status: 'idle' | 'connecting' | 'open' | 'closed';
}

export function ConnectionBanner({ status }: ConnectionBannerProps) {
  if (status !== 'closed' && status !== 'connecting') {
    return null;
  }

  const isConnecting = status === 'connecting';

  return (
    <div
      data-testid="connection-banner"
      className={`flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white ${
        isConnecting ? 'bg-amber-500' : 'bg-red-500'
      }`}
    >
      {isConnecting ? (
        <>
          <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
          Reconnecting...
        </>
      ) : (
        'Connection lost'
      )}
    </div>
  );
}
