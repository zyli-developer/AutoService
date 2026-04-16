import type { ChatMessage } from '../store/chatStore';
import { SystemMessage } from './SystemMessage';

interface MessageBubbleProps {
  message: ChatMessage;
}

function resolveRole(message: ChatMessage): 'customer' | 'agent' | 'operator' | 'system' {
  if (message.sourceRole) return message.sourceRole === undefined ? 'agent' : message.sourceRole;
  // D1 fallback: check source string
  if (message.source.includes('agent')) return 'agent';
  if (message.source.includes('operator')) return 'operator';
  if (message.source.includes('customer')) return 'customer';
  return 'agent';
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.visibility === 'system') {
    return <SystemMessage content={message.content} />;
  }

  const role = resolveRole(message);

  if (role === 'system') {
    return <SystemMessage content={message.content} />;
  }

  const isCustomer = role === 'customer';

  return (
    <div className={`flex px-4 py-1 ${isCustomer ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`
          relative max-w-[75%] rounded-2xl px-4 py-2 text-sm
          ${isCustomer
            ? 'bg-blue-500 text-white rounded-br-sm'
            : 'bg-slate-100 text-slate-800 rounded-bl-sm'
          }
          ${message.status === 'sending' ? 'opacity-60' : ''}
        `}
      >
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {message.status === 'sending' && (
          <span
            data-testid="sending-indicator"
            className="absolute -bottom-4 right-0 text-xs text-slate-400"
          >
            ...
          </span>
        )}
        {message.status === 'failed' && (
          <span
            data-testid="failed-indicator"
            className="absolute -bottom-4 right-0 text-xs text-red-500 font-bold"
          >
            !
          </span>
        )}
      </div>
    </div>
  );
}
