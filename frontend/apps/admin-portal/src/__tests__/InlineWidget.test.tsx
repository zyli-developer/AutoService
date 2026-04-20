import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { InlineWidget } from '../components/chat/InlineWidget';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true });
});

describe('InlineWidget', () => {
  it('renders metric widget', () => {
    render(<InlineWidget block={{ type: 'metric', data: { label: 'CSAT', value: '4.6' } }} />);
    const el = screen.getByTestId('widget-metric');
    expect(el).toHaveTextContent('CSAT');
    expect(el).toHaveTextContent('4.6');
  });

  it('renders alert widget', () => {
    render(<InlineWidget block={{ type: 'alert', data: { text: 'Gray rollout error rate high' } }} />);
    expect(screen.getByTestId('widget-alert')).toHaveTextContent('Gray rollout error rate high');
  });

  it('renders action-launch widget and fires switch-tab on click', async () => {
    const user = userEvent.setup();
    render(
      <InlineWidget
        block={{ type: 'action-launch', data: { text: '需要创建 agent？', target: 'wizard' } }}
      />,
    );
    expect(screen.getByTestId('widget-launch')).toBeInTheDocument();
    await user.click(screen.getByTestId('widget-launch-btn'));
    expect(useAdminStore.getState().activeTab).toBe('wizard');
  });

  it('renders proposal-card widget and fires approve/reject', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(
      <InlineWidget
        block={{
          type: 'proposal-card',
          data: {
            id: 'p-1',
            title: '调整 SLA',
            onApprove,
            onReject,
          },
        }}
      />,
    );
    expect(screen.getByTestId('widget-proposal')).toHaveTextContent('调整 SLA');
    await user.click(screen.getByTestId('widget-proposal-approve'));
    expect(onApprove).toHaveBeenCalledWith('p-1');
    await user.click(screen.getByTestId('widget-proposal-reject'));
    expect(onReject).toHaveBeenCalledWith('p-1');
  });

  it('returns null for unknown block type', () => {
    // @ts-expect-error — intentionally bad input
    const { container } = render(<InlineWidget block={{ type: 'bogus', data: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
