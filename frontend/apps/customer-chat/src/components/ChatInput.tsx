import { useState, useRef } from 'react';
import { useTranslation } from '@autoservice/i18n';

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
}

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
    <div className="web-modal-input-row">
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
      <button
        data-testid="send-button"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
      >
        {t('chat.input.send')}
      </button>
    </div>
  );
}
