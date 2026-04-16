import { useState } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { SystemMessage } from './SystemMessage';
import { formatTimestamp } from '../utils/formatTimestamp';

interface MessageBubbleProps {
  message: ChatMessage;
  showTimestamp?: boolean;
}

function resolveRole(message: ChatMessage): 'customer' | 'agent' | 'operator' | 'system' {
  if (message.sourceRole) return message.sourceRole === undefined ? 'agent' : message.sourceRole;
  // D1 fallback: check source string
  if (message.source.includes('agent')) return 'agent';
  if (message.source.includes('operator')) return 'operator';
  if (message.source.includes('customer')) return 'customer';
  return 'agent';
}

export function MessageBubble({ message, showTimestamp = false }: MessageBubbleProps) {
  const [imgError, setImgError] = useState(false);

  if (message.visibility === 'system') {
    return <SystemMessage content={message.content} />;
  }

  const role = resolveRole(message);

  if (role === 'system') {
    return <SystemMessage content={message.content} />;
  }

  const isCustomer = role === 'customer';
  const attachmentUrl = message.metadata?.attachment_url as string | undefined;
  const isImage = !!attachmentUrl && !imgError;

  return (
    <div className={`flex px-4 py-0.5 ${isCustomer ? 'justify-end' : 'justify-start'}`}>
      <div className="flex flex-col items-end gap-0.5 max-w-[75%]">
        <div
          className={`
            relative rounded-2xl px-4 py-2 text-sm
            ${isCustomer
              ? 'bg-blue-500 text-white rounded-br-sm'
              : 'bg-slate-100 text-slate-800 rounded-bl-sm'
            }
            ${message.status === 'sending' ? 'opacity-60' : ''}
          `}
        >
          {attachmentUrl ? (
            imgError ? (
              <div
                data-testid="image-error-placeholder"
                className="w-48 h-32 bg-slate-200 rounded flex items-center justify-center text-slate-400 text-xs"
              >
                Image unavailable
              </div>
            ) : (
              <img
                data-testid="image-attachment"
                src={attachmentUrl}
                alt="image attachment"
                className="max-w-[240px] rounded-lg"
                loading="lazy"
                onError={() => setImgError(true)}
              />
            )
          ) : (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          )}
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
        {showTimestamp && (
          <span
            data-testid="message-timestamp"
            className="text-[10px] text-slate-400 px-1"
          >
            {formatTimestamp(message.timestamp)}
          </span>
        )}
      </div>
    </div>
  );
}
