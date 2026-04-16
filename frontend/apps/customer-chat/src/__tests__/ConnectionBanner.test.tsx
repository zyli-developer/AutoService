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

  it('TC-048: isReplaying=true shows sync banner with count', () => {
    render(<ConnectionBanner status="open" isReplaying={true} replayCount={5} />);
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
    expect(screen.getByTestId('connection-banner').textContent).toContain('5');
  });

  it('TC-049: isReplaying=false + status=open → no banner', () => {
    render(<ConnectionBanner status="open" isReplaying={false} />);
    expect(screen.queryByTestId('connection-banner')).toBeNull();
  });

  it('TC-050: isReplaying=true takes priority over closed status', () => {
    render(<ConnectionBanner status="closed" isReplaying={true} replayCount={0} />);
    const banner = screen.getByTestId('connection-banner');
    expect(banner.textContent).not.toMatch(/断线|lost|中断/i);
    expect(banner.textContent).toMatch(/同步|Sync|回放/i);
  });
});
