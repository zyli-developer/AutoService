import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatFAB } from '../components/ChatFAB';

describe('ChatFAB', () => {
  it('TC-022-001: clicking the voice FAB fires onCallClick and not onClick', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const onCallClick = vi.fn();
    render(<ChatFAB onClick={onClick} onCallClick={onCallClick} />);

    const voiceBtn = screen.getByTestId('voice-fab');
    await user.click(voiceBtn);

    expect(onCallClick).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it('renders a real <button> (not a <div>) for the voice FAB', () => {
    render(<ChatFAB onClick={vi.fn()} onCallClick={vi.fn()} />);
    const voiceBtn = screen.getByTestId('voice-fab');
    expect(voiceBtn.tagName).toBe('BUTTON');
    expect(voiceBtn).toHaveAttribute('type', 'button');
    expect(voiceBtn).toHaveAttribute('aria-label');
  });

  it('disables the voice FAB when onCallClick is not provided', () => {
    render(<ChatFAB onClick={vi.fn()} />);
    const voiceBtn = screen.getByTestId('voice-fab');
    expect(voiceBtn).toBeDisabled();
  });

  it('chat FAB still fires onClick independently', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const onCallClick = vi.fn();
    render(<ChatFAB onClick={onClick} onCallClick={onCallClick} />);

    const chatBtn = screen.getByRole('button', { name: /open chat|打开聊天/i });
    await user.click(chatBtn);

    expect(onClick).toHaveBeenCalledOnce();
    expect(onCallClick).not.toHaveBeenCalled();
  });
});
