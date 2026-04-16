import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopilotSidebar } from '../components/CopilotSidebar';
import { useOperatorStore, initialState, type Conversation } from '../store/operatorStore';

const makeConv = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: 'conv-001',
  squadId: 'sq-A',
  customerId: 'cust-001',
  mode: 'auto',
  state: 'active',
  lastMessage: '',
  lastMessageSender: '',
  lastActivityTs: '2026-04-16T10:00:00Z',
  ...overrides,
});

beforeEach(() => {
  useOperatorStore.setState({
    ...initialState,
    conversations: {},
    activeCopilotConvId: null,
    copilotMessages: {},
  });
});

describe('Takeover Mode UI', () => {
  it('TC-01: shows "Copilot" title in copilot mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'copilot' }) },
    });
    const send = vi.fn();
    render(<CopilotSidebar send={send} />);
    expect(screen.getByTestId('copilot-title')).toHaveTextContent('Copilot');
    expect(screen.queryByTestId('takeover-indicator')).toBeNull();
  });

  it('TC-02: shows "正式回复" title + TAKEOVER indicator in takeover mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    render(<CopilotSidebar send={send} />);
    expect(screen.getByTestId('copilot-title')).toHaveTextContent('正式回复');
    expect(screen.getByTestId('takeover-indicator')).toHaveTextContent('TAKEOVER');
  });

  it('TC-03: sends send_message frame in takeover mode', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    const user = userEvent.setup();
    render(<CopilotSidebar send={send} />);

    await user.type(screen.getByTestId('copilot-input'), '您好客户');
    await user.click(screen.getByTestId('copilot-send'));

    expect(send).toHaveBeenCalledTimes(1);
    const frame = send.mock.calls[0][0];
    expect(frame.type).toBe('send_message');
    expect(frame.payload.visible_to_customer).toBe(true);
    expect(frame.payload.text).toBe('您好客户');
  });

  it('TC-04: sends operator_message frame in copilot mode', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'copilot' }) },
    });
    const send = vi.fn();
    const user = userEvent.setup();
    render(<CopilotSidebar send={send} />);

    await user.type(screen.getByTestId('copilot-input'), '建议回复');
    await user.click(screen.getByTestId('copilot-send'));

    expect(send).toHaveBeenCalledTimes(1);
    const frame = send.mock.calls[0][0];
    expect(frame.type).toBe('operator_message');
    expect(frame.payload.visible_to_customer).toBeUndefined();
  });

  it('TC-05: placeholder changes with mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    render(<CopilotSidebar send={send} />);
    expect(screen.getByTestId('copilot-input')).toHaveAttribute('placeholder', '正式回复客户...');
  });
});
