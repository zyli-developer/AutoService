import { useTranslation } from '@autoservice/i18n';

interface ChatHeaderProps {
  title?: string;
  status: 'idle' | 'connecting' | 'open' | 'closed';
}

const STATUS_DOT_COLOR: Record<ChatHeaderProps['status'], string> = {
  open: 'bg-green-500',
  connecting: 'bg-amber-400',
  closed: 'bg-red-500',
  idle: 'bg-gray-400',
};

export function ChatHeader({ title, status }: ChatHeaderProps) {
  const { t } = useTranslation();
  const displayTitle = title ?? t('customer.chat.title');
  return (
    <header
      data-testid="chat-header"
      className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white shadow-sm"
    >
      <h1 className="text-base font-semibold text-slate-800">{displayTitle}</h1>
      <div className="flex items-center gap-2">
        <span
          data-testid="status-dot"
          className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT_COLOR[status]}`}
          aria-label={`Connection status: ${status}`}
        />
        <span className="text-xs text-slate-500 capitalize">{status}</span>
      </div>
    </header>
  );
}
