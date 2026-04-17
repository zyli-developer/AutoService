import { describe, it, expect, beforeEach } from 'vitest';
import { useAdminStore, initialState, Notification } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, notifications: [] });
});

describe('adminStore — notifications', () => {
  it('TC-06: addNotification appends', () => {
    const n1: Notification = { id: 'n1', type: 'alert', title: 'A', description: 'desc-A', ts: '2026-01-01T00:00:00Z' };
    const n2: Notification = { id: 'n2', type: 'info', title: 'B', description: 'desc-B', ts: '2026-01-02T00:00:00Z' };

    useAdminStore.getState().addNotification(n1);
    expect(useAdminStore.getState().notifications).toHaveLength(1);
    expect(useAdminStore.getState().notifications[0]).toEqual(n1);

    useAdminStore.getState().addNotification(n2);
    expect(useAdminStore.getState().notifications).toHaveLength(2);
    expect(useAdminStore.getState().notifications[1]).toEqual(n2);
  });

  it('TC-07: clearNotifications empties', () => {
    const n: Notification = { id: 'n1', type: 'command', title: 'C', description: 'desc-C', ts: '2026-01-01T00:00:00Z' };
    useAdminStore.getState().addNotification(n);
    expect(useAdminStore.getState().notifications).toHaveLength(1);

    useAdminStore.getState().clearNotifications();
    expect(useAdminStore.getState().notifications).toHaveLength(0);
  });
});
