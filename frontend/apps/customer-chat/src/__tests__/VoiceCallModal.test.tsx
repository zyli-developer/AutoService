import { describe, it, expect, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VoiceCallModal } from '../components/VoiceCallModal';

function dispatchVoice(data: unknown) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', {
        data,
        origin: 'https://voice.ezagent.chat',
      }),
    );
  });
}

const BASE_CTX = { tenant_id: 't1', customer_id: 'c1', mode: 'e2e' as const, lang: 'zh-CN' };

describe('VoiceCallModal', () => {
  it('TC-022-006: hangup button fires onClose and iframe unmounts when open flips to false', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <VoiceCallModal open={true} onClose={onClose} ctx={BASE_CTX} />,
    );

    expect(screen.getByTestId('voice-iframe')).toBeInTheDocument();

    const hangupBtn = screen.getByTestId('voice-hangup');
    await user.click(hangupBtn);

    expect(onClose).toHaveBeenCalledOnce();

    rerender(<VoiceCallModal open={false} onClose={onClose} ctx={BASE_CTX} />);
    expect(screen.queryByTestId('voice-iframe')).not.toBeInTheDocument();
    expect(screen.queryByTestId('voice-modal')).not.toBeInTheDocument();
  });

  it('TC-022-006: message listener is removed when the modal unmounts', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const { rerender } = render(
      <VoiceCallModal open={true} onClose={vi.fn()} ctx={BASE_CTX} />,
    );
    const addedMessageCalls = addSpy.mock.calls.filter((c) => c[0] === 'message').length;
    expect(addedMessageCalls).toBeGreaterThan(0);

    rerender(<VoiceCallModal open={false} onClose={vi.fn()} ctx={BASE_CTX} />);
    const removedMessageCalls = removeSpy.mock.calls.filter((c) => c[0] === 'message').length;
    expect(removedMessageCalls).toBe(addedMessageCalls);
  });

  it('TC-022-007: NotAllowedError shows the microphone guidance text without a retry button', () => {
    render(<VoiceCallModal open={true} onClose={vi.fn()} ctx={BASE_CTX} />);

    dispatchVoice({
      type: 'as:voice:error',
      code: 'NotAllowedError',
      message: 'denied',
    });

    const errorBox = screen.getByTestId('voice-error');
    expect(errorBox.textContent).toMatch(/microphone|麦克风/i);
    expect(screen.queryByTestId('voice-retry')).not.toBeInTheDocument();
    // Iframe is hidden while error is shown
    expect(screen.queryByTestId('voice-iframe')).not.toBeInTheDocument();
  });

  it('TC-022-008: ws_connect_failed shows a "cannot connect" message with a retry button', async () => {
    const user = userEvent.setup();
    render(<VoiceCallModal open={true} onClose={vi.fn()} ctx={BASE_CTX} />);

    dispatchVoice({
      type: 'as:voice:error',
      code: 'ws_connect_failed',
      message: 'boom',
    });

    const errorBox = screen.getByTestId('voice-error');
    expect(errorBox.textContent).toMatch(/connect|接通/i);

    const retry = screen.getByTestId('voice-retry');
    await user.click(retry);

    // After retry, error clears and iframe remounts
    expect(screen.queryByTestId('voice-error')).not.toBeInTheDocument();
    expect(screen.getByTestId('voice-iframe')).toBeInTheDocument();
  });

  it('iframe carries embed=1 + call_id + ctx params', () => {
    render(<VoiceCallModal open={true} onClose={vi.fn()} ctx={BASE_CTX} />);
    const iframe = screen.getByTestId('voice-iframe') as HTMLIFrameElement;
    const url = new URL(iframe.src);
    expect(url.searchParams.get('embed')).toBe('1');
    expect(url.searchParams.get('tenant_id')).toBe('t1');
    expect(url.searchParams.get('customer_id')).toBe('c1');
    expect(url.searchParams.get('mode')).toBe('e2e');
    const callId = url.searchParams.get('call_id');
    expect(callId).toBeTruthy();
    expect(callId!.length).toBeGreaterThan(8);
  });
});
