import { useState, useEffect } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';

function resolveRole(message: ChatMessage): 'customer' | 'agent' | 'system' {
  if (message.visibility === 'system') return 'system';
  if (message.sourceRole === 'system') return 'system';
  if (message.sourceRole === 'customer') return 'customer';
  if (message.sourceRole === 'agent' || message.sourceRole === 'operator') return 'agent';
  // D1 fallback: check source string
  if (message.source.includes('customer')) return 'customer';
  if (message.source.includes('agent') || message.source.includes('operator')) return 'agent';
  return 'agent';
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const [imgError, setImgError] = useState(false);
  const role = resolveRole(message);
  const attachmentUrl = message.metadata?.attachment_url as string | undefined;
  const isImage = !!attachmentUrl && !imgError;

  useEffect(() => {
    if (!message.justEdited) return;
    const timer = setTimeout(() => {
      useChatStore.getState().clearJustEdited(message.id);
    }, 500);
    return () => clearTimeout(timer);
  }, [message.justEdited, message.id]);

  const statusSuffix =
    message.status === 'sending' ? ' sending' :
    message.status === 'failed' ? ' failed' : '';
  const editedSuffix = message.justEdited ? ' edited' : '';

  return (
    <div
      className={`web-msg ${role}${statusSuffix}${editedSuffix}`}
      data-testid={`msg-${role}`}
    >
      {isImage ? (
        <img
          data-testid="image-attachment"
          src={attachmentUrl}
          alt="image attachment"
          style={{ maxWidth: 200, borderRadius: 8 }}
          loading="lazy"
          onError={() => setImgError(true)}
        />
      ) : attachmentUrl && imgError ? (
        <div data-testid="image-error-placeholder" style={{ color: 'var(--silver)', fontSize: 11 }}>
          Image unavailable
        </div>
      ) : (
        <span>{message.content}</span>
      )}
      {message.status === 'sending' && (
        <span data-testid="sending-indicator" style={{ fontSize: 10, opacity: 0.6 }}> ...</span>
      )}
      {message.status === 'failed' && (
        <span data-testid="failed-indicator" style={{ fontSize: 10, color: 'var(--p)', fontWeight: 700 }}> !</span>
      )}
      {message.isStreaming && (
        <span
          data-testid="streaming-cursor"
          style={{
            display: 'inline-block',
            width: 2,
            height: 14,
            background: 'currentColor',
            marginLeft: 2,
            verticalAlign: 'middle',
            animation: 'pulse 1s infinite',
          }}
        />
      )}
    </div>
  );
}
