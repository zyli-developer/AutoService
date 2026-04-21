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

  it('TC-06: operator message tag follows msg.visibility, not current conv.mode', () => {
    // Regression: StreamMessage used to branch on isTakeover (current mode),
    // causing every historical operator message to change tag when the user
    // hijacked/released. A SIDE suggestion and a PUBLIC hijack reply must
    // keep their own tags independent of the current mode.
    const messages: CopilotMessage[] = [
      { id: 'm-side', text: 'real suggestion', sender: 'operator',
        ts: '2026-04-20T13:09:33Z', visibility: 'side' },
      { id: 'm-public', text: 'hijack reply', sender: 'operator',
        ts: '2026-04-20T13:09:42Z', visibility: 'public' },
      { id: 'm-agent-public', text: 'Hello!', sender: 'agent',
        ts: '2026-04-20T13:09:29Z', visibility: 'public' },
      { id: 'm-agent-side', text: 'gated draft', sender: 'agent',
        ts: '2026-04-20T13:09:30Z', visibility: 'side' },
    ];

    useOperatorStore.setState({
      activeCopilotConvId: 'conv-1',
      conversations: {
        'conv-1': {
          id: 'conv-1', squadId: 'web-support', customerId: 'c1',
          mode: 'takeover', state: 'active',
          lastMessage: '', lastMessageSender: '', lastActivityTs: '',
        } as any,
      },
      copilotMessages: { 'conv-1': messages },
    });

    const send = vi.fn();
    const { rerender } = render(<CopilotView send={send} />);

    // In takeover mode: SIDE operator msg still renders "建议", PUBLIC still renders "driver".
    const takeoverSide = screen.getByTestId('copilot-message-m-side');
    const takeoverPublic = screen.getByTestId('copilot-message-m-public');
    expect(takeoverSide.textContent).toContain('operator.chat.tag.suggestion');
    expect(takeoverPublic.textContent).toContain('driver');
    expect(screen.getByTestId('copilot-message-m-agent-public').textContent).toContain('auto');
    expect(screen.getByTestId('copilot-message-m-agent-side').textContent).toContain('side');

    // Flip to copilot mode: tags MUST NOT change.
    useOperatorStore.setState({
      conversations: {
        'conv-1': {
          id: 'conv-1', squadId: 'web-support', customerId: 'c1',
          mode: 'copilot', state: 'active',
          lastMessage: '', lastMessageSender: '', lastActivityTs: '',
        } as any,
      },
    });
    rerender(<CopilotView send={send} />);

    expect(screen.getByTestId('copilot-message-m-side').textContent).toContain('operator.chat.tag.suggestion');
    expect(screen.getByTestId('copilot-message-m-public').textContent).toContain('driver');
    expect(screen.getByTestId('copilot-message-m-agent-public').textContent).toContain('auto');
    expect(screen.getByTestId('copilot-message-m-agent-side').textContent).toContain('side');
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
