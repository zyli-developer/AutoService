import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceStatusBar } from '../voice/VoiceStatusBar';

describe('VoiceStatusBar', () => {
  it('renders hidden when state is idle', () => {
    const { container } = render(<VoiceStatusBar state="idle" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders listening state text', () => {
    render(<VoiceStatusBar state="listening" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId('voice-status-bar')).toBeInTheDocument();
    expect(screen.getByLabelText(/hang ?up|挂断/i)).toBeInTheDocument();
  });

  it('shows skip button only in speaking state', () => {
    const { rerender } = render(<VoiceStatusBar state="thinking" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByLabelText(/skip|跳过/i)).toBeNull();
    rerender(<VoiceStatusBar state="speaking" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByLabelText(/skip|跳过/i)).toBeInTheDocument();
  });

  it('shows retry button in error state', () => {
    const onRetry = vi.fn();
    render(<VoiceStatusBar state="error" errorReason="mic_denied" onSkip={vi.fn()} onHangup={vi.fn()} onRetry={onRetry} />);
    fireEvent.click(screen.getByLabelText(/retry|重试/i));
    expect(onRetry).toHaveBeenCalled();
  });
});
