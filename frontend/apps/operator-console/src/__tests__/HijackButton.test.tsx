import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopilotView } from '../components/CopilotView';
import { HijackButton } from '../components/HijackButton';
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
    expect(btn).toHaveTextContent(/抢.?单/);
  });

  it('TC-02: clicking hijack button calls send with correct frame', async () => {
    useOperatorStore.setState({
      activeCopilotConvId: 'conv-042',
      operatorId: 'op1',
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

describe('HijackButton dual-state', () => {
  beforeEach(() => {
    useOperatorStore.setState({ ...initialState });
  });

  function addConv(mode: 'auto' | 'copilot' | 'takeover', id = 'c1') {
    const conv = makeConv({ id, mode });
    useOperatorStore.setState({
      operatorId: 'op1',
      conversations: { [id]: conv },
    });
  }

  it('shows 释放回 AI when mode is takeover and dispatches /release', async () => {
    addConv('takeover');
    const send = vi.fn();
    render(<HijackButton conversationId="c1" send={send} />);

    const btn = screen.getByTestId('btn-release-c1');
    expect(btn.textContent).toMatch(/释放.*回.*AI/);
    const user = userEvent.setup();
    await user.click(btn);
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'operator_command',
        payload: expect.objectContaining({
          conversation_id: 'c1',
          command: '/release',
        }),
      }),
    );
  });

  it('shows 抢单 when mode is auto and dispatches /hijack', async () => {
    addConv('auto');
    const send = vi.fn();
    render(<HijackButton conversationId="c1" send={send} />);
    const btn = screen.getByTestId('btn-hijack-c1');
    expect(btn.textContent).toMatch(/抢.*单/);
    const user = userEvent.setup();
    await user.click(btn);
    expect(send.mock.calls[0][0].payload.command).toBe('/hijack');
  });

  it('shows 抢单 when mode is copilot and dispatches /hijack', async () => {
    addConv('copilot');
    const send = vi.fn();
    render(<HijackButton conversationId="c1" send={send} />);
    const btn = screen.getByTestId('btn-hijack-c1');
    expect(btn.textContent).toMatch(/抢.*单/);
    const user = userEvent.setup();
    await user.click(btn);
    expect(send.mock.calls[0][0].payload.command).toBe('/hijack');
  });

  it('is disabled when operatorId is null', () => {
    const conv = makeConv({ id: 'c1', mode: 'auto' });
    useOperatorStore.setState({ operatorId: null, conversations: { c1: conv } });
    render(<HijackButton conversationId="c1" send={vi.fn()} />);
    expect(screen.getByTestId('btn-hijack-c1')).toBeDisabled();
  });
});
