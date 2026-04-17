import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TypingIndicator } from '../components/TypingIndicator';

describe('TypingIndicator', () => {
  it('TC-006: renders when visible=true', () => {
    render(<TypingIndicator visible={true} />);
    expect(screen.getByTestId('typing-indicator')).toBeInTheDocument();
  });

  it('TC-007: does not render when visible=false', () => {
    render(<TypingIndicator visible={false} />);
    expect(screen.queryByTestId('typing-indicator')).not.toBeInTheDocument();
  });
});
