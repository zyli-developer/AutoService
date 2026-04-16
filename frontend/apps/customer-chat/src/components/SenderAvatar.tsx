interface SenderAvatarProps {
  name?: string;
  avatarUrl?: string;
}

export function SenderAvatar({ name, avatarUrl }: SenderAvatarProps) {
  const initial = (name ?? '?')[0].toUpperCase();

  if (avatarUrl) {
    return (
      <div data-testid="sender-avatar" className="flex-shrink-0">
        <img
          src={avatarUrl}
          alt={name ?? 'avatar'}
          className="w-8 h-8 rounded-full object-cover"
        />
      </div>
    );
  }

  return (
    <div
      data-testid="sender-avatar"
      className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-300 flex items-center justify-center text-xs font-medium text-slate-600"
    >
      {initial}
    </div>
  );
}
