import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopilotView } from '../components/CopilotView';
import { IMInput } from '../components/IMInput';
import { useOperatorStore, initialState, type CopilotMessage } from '../store/operatorStore';

beforeEach(() => {
  useOperatorStore.setState({ ...initialState });
});

describe('CopilotView', () => {
  it('TC-01: not rendered when activeCopilotConvId is null', () => {
    const send = vi.fn();
    render(<CopilotView send={send} />);
    expect(screen.queryByTestId('copilot-sidebar')).toBeNull();
  });

  it('TC-02: rendered when activeCopilotConvId is set', () => {
    useOperatorStore.setState({ activeCopilotConvId: 'conv-1' });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    expect(screen.getByTestId('copilot-sidebar')).toBeInTheDocument();
  });

  it('TC-03: messages displayed in order', () => {
    const messages: CopilotMessage[] = [
      { id: 'msg-1', text: 'first message', sender: 'customer', ts: '2026-04-16T10:00:00Z' },
      { id: 'msg-2', text: 'second message', sender: 'agent', ts: '2026-04-16T10:01:00Z' },
      { id: 'msg-3', text: 'third message', sender: 'operator', ts: '2026-04-16T10:02:00Z' },
    ];
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-1',
      copilotMessages: { 'conv-1': messages },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);

    const msgElements = [
      screen.getByTestId('copilot-message-msg-1'),
      screen.getByTestId('copilot-message-msg-2'),
      screen.getByTestId('copilot-message-msg-3'),
    ];
    expect(msgElements[0]).toBeInTheDocument();
    expect(msgElements[1]).toBeInTheDocument();
    expect(msgElements[2]).toBeInTheDocument();

    expect(msgElements[0].compareDocumentPosition(msgElements[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(msgElements[1].compareDocumentPosition(msgElements[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('TC-04: typing in IMInput and clicking send calls the send callback', async () => {
    useOperatorStore.setState({ activeCopilotConvId: 'conv-1' });
    const send = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <CopilotView send={send} />
        <IMInput send={send} />
      </>
    );

    const input = screen.getByTestId('copilot-input');
    await user.type(input, 'hello world');
    await user.click(screen.getByTestId('copilot-send'));

    expect(send).toHaveBeenCalled();
    const frame = send.mock.calls[send.mock.calls.length - 1][0];
    expect(frame.type).toBe('operator_message');
    expect(frame.v).toBe(1);
    expect(frame.payload.conversation_id).toBe('conv-1');
    expect(frame.payload.content).toBe('hello world');

    expect(screen.getByTestId('copilot-input')).toHaveValue('');
  });

  it('TC-05: close button calls closeCopilot', async () => {
    useOperatorStore.setState({ activeCopilotConvId: 'conv-1' });
    const send = vi.fn();
    const user = userEvent.setup();
    render(<CopilotView send={send} />);

    await user.click(screen.getByTestId('copilot-close'));
    expect(useOperatorStore.getState().activeCopilotConvId).toBeNull();
  });
});
