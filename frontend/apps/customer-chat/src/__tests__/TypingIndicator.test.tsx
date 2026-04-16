import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TypingIndicator } from '../components/TypingIndicator';
import { MessageList } from '../components/MessageList';
import { useChatStore, initialState } from '../store/chatStore';

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

describe('TypingIndicator', () => {
  it('TC-006: renders when visible=true', () => {
    render(<TypingIndicator visible={true} />);
    expect(screen.getByTestId('typing-indicator')).toBeInTheDocument();
  });

  it('TC-007: does not render when visible=false', () => {
    render(<TypingIndicator visible={false} />);
    expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument();
  });

  it('TC-008: MessageList shows typing-indicator when store isAgentTyping=true', () => {
    useChatStore.setState({ ...initialState, isAgentTyping: true });
    render(<MessageList messages={[]} />);
    expect(screen.getByTestId('typing-indicator')).toBeInTheDocument();
  });
});
