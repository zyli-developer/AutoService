import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopilotView } from '../components/CopilotView';
import { useOperatorStore, initialState, type Conversation } from '../store/operatorStore';

const makeConv = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: 'conv-001',
  squadId: 'sq-A',
  customerId: 'cust-alice',
  mode: 'auto',
  state: 'active',
  lastMessage: '',
  lastMessageSender: '',
  lastActivityTs: '2026-04-16T10:00:00Z',
  ...overrides,
});

beforeEach(() => {
  useOperatorStore.setState({ ...initialState });
});

describe('Hijack in CopilotView', () => {
  it('TC-01: hijack button renders with /hijack label', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'auto' }) },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    const btn = screen.getByTestId('btn-hijack-conv-001');
    expect(btn).toHaveTextContent(/\u62A2\u5355/);
  });

  it('TC-02: clicking hijack button calls send with correct frame', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-042',
      conversations: { 'conv-042': makeConv({ id: 'conv-042', mode: 'auto' }) },
    });
    const send = vi.fn();
    const user = userEvent.setup();
    render(<CopilotView send={send} />);
    await user.click(screen.getByTestId('btn-hijack-conv-042'));
    expect(send).toHaveBeenCalledTimes(1);
    const frame = send.mock.calls[0][0];
    expect(frame.v).toBe(1);
    expect(frame.type).toBe('operator_command');
    expect(frame.payload.command).toBe('/hijack');
    expect(frame.payload.conversation_id).toBe('conv-042');
  });

  it('TC-04: hijack button not shown when mode=takeover', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'takeover' }) },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    expect(screen.queryByTestId('btn-hijack-conv-001')).toBeNull();
  });

  it('TC-05: hijack button shown when mode=auto', () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-001',
      conversations: { 'conv-001': makeConv({ mode: 'auto' }) },
    });
    const send = vi.fn();
    render(<CopilotView send={send} />);
    expect(screen.getByTestId('btn-hijack-conv-001')).toBeInTheDocument();
  });
});
