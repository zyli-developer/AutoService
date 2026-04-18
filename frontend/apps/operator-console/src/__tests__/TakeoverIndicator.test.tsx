import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { TakeoverIndicator } from '../components/TakeoverIndicator';
import { useOperatorStore } from '../store/operatorStore';

describe('TakeoverIndicator', () => {
  beforeEach(() => {
    useOperatorStore.getState().logout();
  });

  function addConv(mode: 'auto' | 'copilot' | 'takeover', armed = false, id = 'c1') {
    useOperatorStore.getState().addConversation({
      id, squadId: 'web-support', customerId: 'cust1',
      mode, state: 'active', lastMessage: '', lastMessageSender: '', lastActivityTs: '',
    } as any);
    if (armed) {
      useOperatorStore.getState().setTakeoverArmed(id, {
        armedAt: new Date(Date.now() - 1000).toISOString(), // 1s ago
        idleMs: 8000,
        warningMs: 3000,
      });
    }
  }

  it('renders nothing when mode is auto', () => {
    addConv('auto');
    const { container } = render(<TakeoverIndicator conversationId="c1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders pulse badge when mode is takeover (no countdown yet)', () => {
    addConv('takeover');
    render(<TakeoverIndicator conversationId="c1" />);
    expect(screen.getByTestId('takeover-indicator')).toBeInTheDocument();
    expect(screen.queryByTestId('takeover-countdown')).not.toBeInTheDocument();
  });

  it('renders countdown chip showing remaining seconds when armed', () => {
    addConv('takeover', true);
    render(<TakeoverIndicator conversationId="c1" />);
    const chip = screen.getByTestId('takeover-countdown');
    // armedAt was 1s ago, idle 8s → ~7s remaining; allow 6-8s tolerance for timing
    const text = chip.textContent ?? '';
    const match = text.match(/^(\d+)s$/);
    expect(match).not.toBeNull();
    const n = Number(match![1]);
    expect(n).toBeGreaterThanOrEqual(6);
    expect(n).toBeLessThanOrEqual(8);
  });
});
