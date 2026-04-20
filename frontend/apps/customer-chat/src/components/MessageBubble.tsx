import { useState, useEffect } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';

function resolveRole(message: ChatMessage): 'customer' | 'agent' | 'operator' | 'system' {
  if (message.visibility === 'system') return 'system';
  if (message.sourceRole === 'system') return 'system';
  if (message.sourceRole === 'customer') return 'customer';
  if (message.sourceRole === 'operator') return 'operator';
  if (message.sourceRole === 'agent') return 'agent';
  // D1 fallback: check source string
  if (message.source.includes('customer')) return 'customer';
  if (message.source.includes('operator')) return 'operator';
  if (message.source.includes('agent')) return 'agent';
  return 'agent';
}

function avatarLabel(role: string): string {
  if (role === 'customer') return '我';
  if (role === 'operator') return '李';
  if (role === 'agent') return '店';
  return '·';
}

function whoLabel(role: string): { name: string; tag?: string; tagKind?: 'ai' | 'op' } {
  if (role === 'customer') return { name: '我' };
  if (role === 'operator') return { name: '客服小李', tag: '人工', tagKind: 'op' };
  if (role === 'agent') return { name: 'mystore 客服', tag: 'AI', tagKind: 'ai' };
  return { name: '系统' };
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

  if (role === 'system') {
    return (
      <div
        className={`web-msg system${statusSuffix}${editedSuffix}`}
        data-testid="msg-system"
      >
        <span>{message.content}</span>
      </div>
    );
  }

  const { name, tag, tagKind } = whoLabel(role);

  return (
    <div
      className={`w-msg ${role}${statusSuffix}${editedSuffix}`}
      data-testid={`msg-${role}`}
    >
      <div className={`w-msg-av ${role}`}>{avatarLabel(role)}</div>
      <div className="w-msg-body">
        <div className="w-msg-who">
          <span>{name}</span>
          {tag && <span className={`w-msg-tag ${tagKind ?? ''}`}>{tag}</span>}
        </div>
        <div className={`web-msg ${role}${statusSuffix}${editedSuffix}`}>
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
            <div data-testid="image-error-placeholder" style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
              Image unavailable
            </div>
          ) : (
            <span>{message.content}</span>
          )}
          {message.status === 'sending' && (
            <span data-testid="sending-indicator" style={{ fontSize: 10, opacity: 0.6 }}> ...</span>
          )}
          {message.status === 'failed' && (
            <span data-testid="failed-indicator" style={{ fontSize: 10, color: 'var(--vermillion-500)', fontWeight: 500 }}> !</span>
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
      </div>
    </div>
  );
}
