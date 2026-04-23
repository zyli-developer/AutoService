import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceStatusBar } from '../voice/VoiceStatusBar';

describe('VoiceStatusBar', () => {
  it('renders hidden when state is idle', () => {
    const { container } = render(<VoiceStatusBar state="idle" errorReason={null} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders listening state text', () => {
    render(<VoiceStatusBar state="listening" errorReason={null} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId('voice-status-bar')).toBeInTheDocument();
    expect(screen.getByLabelText(/hang ?up|挂断/i)).toBeInTheDocument();
  });

  it('does NOT render a skip button — barge-in is automatic via user speech', () => {
    render(<VoiceStatusBar state="speaking" errorReason={null} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByLabelText(/skip|跳过/i)).toBeNull();
  });

  it('shows retry button in error state', () => {
    const onRetry = vi.fn();
    render(<VoiceStatusBar state="error" errorReason="mic_denied" onHangup={vi.fn()} onRetry={onRetry} />);
    fireEvent.click(screen.getByLabelText(/retry|重试/i));
    expect(onRetry).toHaveBeenCalled();
  });
});
