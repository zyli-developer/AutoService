import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopilotView } from '../components/CopilotView';
import { IMInput } from '../components/IMInput';
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
  it('TC-01: shows copilot subtitle in copilot mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'copilot' }) },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    const header = screen.getByTestId('copilot-header');
    expect(header.textContent).toContain('copilot');
    expect(screen.queryByTestId('takeover-indicator')).toBeNull();
  });

  it('TC-02: shows TAKEOVER indicator in takeover mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    expect(screen.getByTestId('takeover-indicator')).toHaveTextContent('TAKEOVER');
  });

  it('TC-03: sends operator_message frame in takeover mode', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    const user = userEvent.setup();
    // CopilotView renders IMInput internally; rendering it again here
    // would create duplicate `copilot-input` testids.
    render(<CopilotView send={send} />);

    await user.type(screen.getByTestId('copilot-input'), '您好客户');
    await user.click(screen.getByTestId('copilot-send'));

    const calls = send.mock.calls;
    const frame = calls[calls.length - 1][0];
    expect(frame.type).toBe('operator_message');
    expect(frame.payload.conversation_id).toBe('conv-001');
    expect(frame.payload.content).toBe('您好客户');
  });

  it('TC-04: sends operator_message frame in copilot mode', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'copilot' }) },
    });
    const send = vi.fn();
    const user = userEvent.setup();
    // See TC-03 — CopilotView already includes IMInput.
    render(<CopilotView send={send} />);

    await user.type(screen.getByTestId('copilot-input'), '建议回复');
    await user.click(screen.getByTestId('copilot-send'));

    const calls = send.mock.calls;
    const frame = calls[calls.length - 1][0];
    expect(frame.type).toBe('operator_message');
    expect(frame.payload.conversation_id).toBe('conv-001');
    expect(frame.payload.content).toBe('建议回复');
  });

  it('TC-05: placeholder changes with mode', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    render(<IMInput send={send} />);
    const input = screen.getByTestId('copilot-input');
    expect(input.getAttribute('placeholder')).toContain('人工');
  });
});
