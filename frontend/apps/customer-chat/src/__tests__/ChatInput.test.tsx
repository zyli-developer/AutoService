import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatInput } from '../components/ChatInput';

describe('ChatInput', () => {
  it('TC-014: clicking Send button calls onSend with input value and clears input', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByTestId('chat-input');
    const sendBtn = screen.getByTestId('send-button');

    await user.type(input, 'Hello world');
    await user.click(sendBtn);

    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith('Hello world');
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('TC-015: pressing Enter (without Shift) submits the message', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByTestId('chat-input');
    await user.type(input, 'Enter message');
    await user.keyboard('{Enter}');

    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith('Enter message');
  });

  it('TC-016: empty input does not call onSend', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const sendBtn = screen.getByTestId('send-button');
    await user.click(sendBtn);

    expect(onSend).not.toHaveBeenCalled();
  });
});
