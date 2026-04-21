import { useState, useEffect } from 'react';
import { useTranslation } from '@autoservice/i18n';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';

type Role = 'customer' | 'agent' | 'operator' | 'system';

function resolveRole(message: ChatMessage): Role {
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

export function MessageBubble({ message }: { message: ChatMessage }) {
  const { t } = useTranslation();
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

  const avatarLabel = t(`customer.chat.avatar.${role === 'customer' ? 'me' : role === 'operator' ? 'operator' : 'agent'}`);
  const name = t(`customer.chat.sender.${role === 'customer' ? 'me' : role === 'operator' ? 'operator' : 'agent'}`);
  const tag = role === 'operator' ? t('customer.chat.tag.operator') : role === 'agent' ? t('customer.chat.tag.agent') : null;
  const tagKind = role === 'operator' ? 'op' : role === 'agent' ? 'ai' : '';

  return (
    <div
      className={`w-msg ${role}${statusSuffix}${editedSuffix}`}
      data-testid={`msg-${role}`}
    >
      <div className={`w-msg-av ${role}`}>{avatarLabel}</div>
      <div className="w-msg-body">
        <div className="w-msg-who">
          <span>{name}</span>
          {tag && <span className={`w-msg-tag ${tagKind}`}>{tag}</span>}
        </div>
        <div className={`web-msg ${role}${statusSuffix}${editedSuffix}`}>
          {isImage ? (
            <img
              data-testid="image-attachment"
              src={attachmentUrl}
              alt={t('customer.chat.image_attachment')}
              style={{ maxWidth: 200, borderRadius: 8 }}
              loading="lazy"
              onError={() => setImgError(true)}
            />
          ) : attachmentUrl && imgError ? (
            <div data-testid="image-error-placeholder" style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
              {t('image.error')}
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
