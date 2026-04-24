import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatFAB } from '../components/ChatFAB';

describe('ChatFAB', () => {
  it('renders a button with the customer.chat.open aria-label', () => {
    render(<ChatFAB onClick={vi.fn()} />);
    const btn = screen.getByRole('button', { name: /open chat|打开聊天/i });
    expect(btn).toBeInTheDocument();
    expect(btn.tagName).toBe('BUTTON');
    expect(btn).toHaveAttribute('type', 'button');
    expect(btn).toHaveAttribute('aria-label');
  });

  it('fires onClick when clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<ChatFAB onClick={onClick} />);
    await user.click(screen.getByRole('button', { name: /open chat|打开聊天/i }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('adds the highlight class when highlight=true', () => {
    render(<ChatFAB onClick={vi.fn()} highlight={true} />);
    const btn = screen.getByRole('button', { name: /open chat|打开聊天/i });
    expect(btn.className).toContain('highlight');
  });

  it('does not have the highlight class when highlight=false', () => {
    render(<ChatFAB onClick={vi.fn()} highlight={false} />);
    const btn = screen.getByRole('button', { name: /open chat|打开聊天/i });
    expect(btn.className).not.toContain('highlight');
  });
});
