import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatFAB } from '../components/ChatFAB';

describe('ChatFAB', () => {
  it('renders the FAB button', () => {
    render(<ChatFAB onClick={vi.fn()} />);
    expect(screen.getByTestId('chat-fab')).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<ChatFAB onClick={onClick} />);
    await user.click(screen.getByTestId('chat-fab'));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('adds highlight class when highlight=true', () => {
    render(<ChatFAB onClick={vi.fn()} highlight={true} />);
    const fab = screen.getByTestId('chat-fab');
    expect(fab.className).toContain('highlight');
  });

  it('does not have highlight class when highlight=false', () => {
    render(<ChatFAB onClick={vi.fn()} highlight={false} />);
    const fab = screen.getByTestId('chat-fab');
    expect(fab.className).not.toContain('highlight');
  });
});
