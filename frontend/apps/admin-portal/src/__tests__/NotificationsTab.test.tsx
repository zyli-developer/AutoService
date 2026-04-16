import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NotificationsTab } from '../components/NotificationsTab';
import { useAdminStore, initialState } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, notifications: [] });
});

describe('NotificationsTab', () => {
  it('TC-01: empty state shows "暂无通知"', () => {
    render(<NotificationsTab />);
    expect(screen.getByText('暂无通知')).toBeInTheDocument();
  });

  it('TC-02: notifications render in list', () => {
    useAdminStore.setState({
      notifications: [
        { id: 'n1', type: 'alert', title: '警告A', description: '描述A', ts: '2026-01-01T00:00:00Z' },
        { id: 'n2', type: 'info', title: '信息B', description: '描述B', ts: '2026-01-02T00:00:00Z' },
      ],
    });
    render(<NotificationsTab />);
    expect(screen.getByTestId('notification-item-n1')).toBeInTheDocument();
    expect(screen.getByTestId('notification-item-n2')).toBeInTheDocument();
    expect(screen.getByText('警告A')).toBeInTheDocument();
    expect(screen.getByText('信息B')).toBeInTheDocument();
  });

  it('TC-03: /rules command adds notification', async () => {
    const user = userEvent.setup();
    render(<NotificationsTab />);
    await user.type(screen.getByTestId('notification-input'), '/rules');
    await user.click(screen.getByTestId('notification-send'));
    expect(screen.getByText('规则配置已更新')).toBeInTheDocument();
  });

  it('TC-04: /status command adds notification', async () => {
    const user = userEvent.setup();
    render(<NotificationsTab />);
    await user.type(screen.getByTestId('notification-input'), '/status');
    await user.click(screen.getByTestId('notification-send'));
    expect(screen.getByText('系统状态：正常')).toBeInTheDocument();
  });

  it('TC-05: clearNotifications empties the list', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<NotificationsTab />);
    await user.type(screen.getByTestId('notification-input'), '/rules');
    await user.click(screen.getByTestId('notification-send'));
    expect(screen.getByText('规则配置已更新')).toBeInTheDocument();

    useAdminStore.getState().clearNotifications();
    rerender(<NotificationsTab />);
    expect(screen.getByText('暂无通知')).toBeInTheDocument();
  });
});
