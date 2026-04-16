import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConnectionBanner } from '../components/ConnectionBanner';

describe('ConnectionBanner', () => {
  it('TC-019: renders nothing when status is open or idle', () => {
    const { container: c1 } = render(<ConnectionBanner status="open" />);
    expect(c1.firstChild).toBeNull();

    const { container: c2 } = render(<ConnectionBanner status="idle" />);
    expect(c2.firstChild).toBeNull();
  });

  it('TC-020: renders Reconnecting... when connecting and Connection lost when closed', () => {
    const { rerender } = render(<ConnectionBanner status="connecting" />);
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();

    rerender(<ConnectionBanner status="closed" />);
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
    expect(screen.getByText(/Connection lost/)).toBeInTheDocument();
  });
});
