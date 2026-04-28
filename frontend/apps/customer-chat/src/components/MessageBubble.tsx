import { useState, useEffect, useRef } from 'react';
import { MarkdownText } from '@autoservice/ui-components';
import { useTranslation } from '@autoservice/i18n';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';

/** Per-character reveal interval for the voice typewriter animation.
 *  Tuned for spoken Chinese (~4-5 chars/sec) so the visible text reveal
 *  roughly matches the audio playback pace. Tweak if voices are mostly
 *  English or the speaker pace is faster. */
const _VOICE_TYPEWRITER_INTERVAL_MS = 60;
/** Reveal this many characters per tick — combined with the interval
 *  above the effective speed is ~33 chars/sec at 60ms × 2 chars. Plenty
 *  visible "growth" without flooding requestAnimationFrame. */
const _VOICE_TYPEWRITER_STEP = 2;

/** Hook: when ``enabled`` is true, animate ``fullContent`` from 0 chars
 *  up to its full length, returning the currently-revealed prefix. When
 *  disabled, returns the full content immediately. */
function useTypewriter(fullContent: string, enabled: boolean): string {
  const [visible, setVisible] = useState(() => (enabled ? '' : fullContent));
  const lastContentRef = useRef(fullContent);

  useEffect(() => {
    if (!enabled) {
      setVisible(fullContent);
      lastContentRef.current = fullContent;
      return;
    }
    // Content changed beneath us (rare — voice messages don't get
    // edited mid-flight today, but be defensive). Reset and re-animate.
    if (lastContentRef.current !== fullContent) {
      setVisible('');
      lastContentRef.current = fullContent;
    }
  }, [fullContent, enabled]);

  useEffect(() => {
    if (!enabled) return;
    if (visible.length >= fullContent.length) return;
    const timer = setInterval(() => {
      setVisible((prev) => {
        if (prev.length >= fullContent.length) return prev;
        return fullContent.slice(0, prev.length + _VOICE_TYPEWRITER_STEP);
      });
    }, _VOICE_TYPEWRITER_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fullContent, enabled, visible.length]);

  return visible;
}

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
  const brandName = useChatStore((s) => s.brandName);
  const attachmentUrl = message.metadata?.attachment_url as string | undefined;
  const isImage = !!attachmentUrl && !imgError;

  // Voice agent replies are sent in one shot from the backend (so
  // Doubao TTS plays as one continuous synth), but the chat bubble
  // gets a client-side typewriter reveal so the visual matches the
  // audio progressively unfolding. Trigger only on agent voice
  // messages (metadata.voice=true and not a greeting echo, since the
  // greeting plays before the user opens chat).
  const isVoiceAgent = role === 'agent'
    && message.metadata?.voice === true
    && !isImage;
  const typewriterContent = useTypewriter(message.content, isVoiceAgent);
  const displayContent = isVoiceAgent ? typewriterContent : message.content;
  // Show the streaming cursor while the typewriter is still revealing.
  const typewriterActive = isVoiceAgent
    && typewriterContent.length < message.content.length;

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

  // Agent (AI) bubble: when the tenant has a configured brand, substitute
  // it into the sender label + avatar so the widget reads as the
  // merchant's brand rather than a hardcoded placeholder.  Customer and
  // operator roles keep their fixed i18n strings.
  const avatarLabel = role === 'agent' && brandName
    ? Array.from(brandName)[0] ?? t('customer.chat.avatar.agent')
    : t(`customer.chat.avatar.${role === 'customer' ? 'me' : role === 'operator' ? 'operator' : 'agent'}`);
  const name = role === 'agent'
    ? (brandName
        ? t('customer.chat.sender.agent', { brand: brandName })
        : t('customer.chat.sender.agent_generic'))
    : t(`customer.chat.sender.${role === 'customer' ? 'me' : 'operator'}`);
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
            <MarkdownText>{displayContent}</MarkdownText>
          )}
          {message.status === 'sending' && (
            <span data-testid="sending-indicator" style={{ fontSize: 10, opacity: 0.6 }}> ...</span>
          )}
          {message.status === 'failed' && (
            <span data-testid="failed-indicator" style={{ fontSize: 10, color: 'var(--vermillion-500)', fontWeight: 500 }}> !</span>
          )}
          {(message.isStreaming || typewriterActive) && (
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
