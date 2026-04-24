import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TakeoverWarning } from '../components/TakeoverWarning';
import { useOperatorStore } from '../store/operatorStore';

describe('TakeoverWarning', () => {
  beforeEach(() => {
    useOperatorStore.getState().logout();
    useOperatorStore.getState().login('op42', 'tok');
  });

  function addConvWithWarning(convId = 'c1', takeoverOperatorId: string | null = 'op42') {
    useOperatorStore.getState().addConversation({
      id: convId, squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active',
      lastMessage: '', lastMessageSender: '', lastActivityTs: '',
      takeoverOperatorId,
    } as any);
    useOperatorStore.getState().setTakeoverWarning(convId, {
      remainingMs: 5000,
      reason: 'idle',
      warningFrameId: 'f1',
      armedAt: '2026-04-17T00:00:00Z',
    });
  }

  it('renders banner when current operator is the takeover operator and warning is active', () => {
    addConvWithWarning();
    render(<TakeoverWarning conversationId="c1" send={vi.fn()} />);
    expect(screen.getByTestId('takeover-warning-c1')).toBeInTheDocument();
  });

  it('does not render when there is no warning', () => {
    useOperatorStore.getState().addConversation({
      id: 'c1', squadId: 'web-support', customerId: 'cust1',
      mode: 'takeover', state: 'active',
      lastMessage: '', lastMessageSender: '', lastActivityTs: '',
      takeoverOperatorId: 'op42',
    } as any);
    const { container } = render(<TakeoverWarning conversationId="c1" send={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('does not render when current operator is not the takeover operator', () => {
    addConvWithWarning('c1', 'opOther');
    const { container } = render(<TakeoverWarning conversationId="c1" send={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('clicking 继续接管 sends client_ack with action=continue', async () => {
    addConvWithWarning();
    const send = vi.fn();
    render(<TakeoverWarning conversationId="c1" send={send} />);
    await userEvent.click(screen.getByTestId('takeover-warning-continue'));
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'client_ack',
        payload: expect.objectContaining({
          action: 'continue',
          conversation_id: 'c1',
        }),
      }),
    );
  });

  it('clicking 释放 sends /release operator_command', async () => {
    addConvWithWarning();
    const send = vi.fn();
    render(<TakeoverWarning conversationId="c1" send={send} />);
    await userEvent.click(screen.getByTestId('takeover-warning-release'));
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'operator_command',
        payload: expect.objectContaining({
          conversation_id: 'c1',
          command: '/release',
          operator_id: 'op42',
        }),
      }),
    );
  });
});
