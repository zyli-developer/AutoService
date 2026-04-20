import { useState, useRef } from 'react';
import { useTranslation } from '@autoservice/i18n';

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
}

const PicIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-5-5L5 21" />
  </svg>
);
const AttachIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);
const EmojiIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" />
  </svg>
);
const SendIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 2 11 13M22 2 15 22l-4-9-9-4Z" />
  </svg>
);

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { t } = useTranslation();

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 80)}px`;
  };

  return (
    <>
      <div className="w-comp-box">
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          placeholder={disabled ? t('chat.input.placeholder.connecting') : t('chat.input.placeholder')}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
        />
        <div className="w-comp-tools">
          <button type="button" className="w-tool-btn" title="图片" aria-label="Insert picture" disabled={disabled}>
            <PicIcon />
          </button>
          <button type="button" className="w-tool-btn" title="附件" aria-label="Attach file" disabled={disabled}>
            <AttachIcon />
          </button>
          <button type="button" className="w-tool-btn" title="表情" aria-label="Insert emoji" disabled={disabled}>
            <EmojiIcon />
          </button>
        </div>
        <button
          type="button"
          className="w-send"
          data-testid="send-button"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          aria-label={t('chat.input.send')}
          title={t('chat.input.send')}
        >
          <SendIcon />
        </button>
      </div>
      <div className="w-foot">
        <span>按 Enter 发送 · Shift+Enter 换行</span>
        <span className="w-foot-powered">
          powered by <b>OneSyn · autoservice</b>
        </span>
      </div>
    </>
  );
}
