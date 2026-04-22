import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VoiceCallModal } from '../components/VoiceCallModal';

describe('VoiceCallModal · postMessage listener lifecycle', () => {
  it('TC-022-010: 5x open/close cycles — message listener add/remove counts match, iframe fully torn down each time', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const ctx = { tenant_id: 't1', customer_id: 'c1', mode: 'e2e' as const };

    const { rerender } = render(
      <VoiceCallModal open={false} onClose={vi.fn()} ctx={ctx} />,
    );

    for (let i = 0; i < 5; i++) {
      rerender(<VoiceCallModal open={true} onClose={vi.fn()} ctx={ctx} />);
      expect(screen.getByTestId('voice-iframe')).toBeInTheDocument();

      rerender(<VoiceCallModal open={false} onClose={vi.fn()} ctx={ctx} />);
      expect(screen.queryByTestId('voice-iframe')).not.toBeInTheDocument();
      expect(screen.queryByTestId('voice-modal')).not.toBeInTheDocument();
    }

    const added = addSpy.mock.calls.filter((c) => c[0] === 'message').length;
    const removed = removeSpy.mock.calls.filter((c) => c[0] === 'message').length;
    expect(added).toBeGreaterThan(0);
    expect(added).toBe(removed);
  });

  it('rotates call_id on every open (not reusing stale id across calls)', () => {
    const ctx = { tenant_id: 't1' };
    const { rerender } = render(
      <VoiceCallModal open={true} onClose={vi.fn()} ctx={ctx} />,
    );
    const firstId = new URL(
      (screen.getByTestId('voice-iframe') as HTMLIFrameElement).src,
    ).searchParams.get('call_id');

    rerender(<VoiceCallModal open={false} onClose={vi.fn()} ctx={ctx} />);
    rerender(<VoiceCallModal open={true} onClose={vi.fn()} ctx={ctx} />);
    const secondId = new URL(
      (screen.getByTestId('voice-iframe') as HTMLIFrameElement).src,
    ).searchParams.get('call_id');

    expect(firstId).toBeTruthy();
    expect(secondId).toBeTruthy();
    expect(secondId).not.toBe(firstId);
  });
});
