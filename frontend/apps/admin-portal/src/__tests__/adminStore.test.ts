import { describe, it, expect, beforeEach } from 'vitest';
import { useAdminStore, initialState } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState(initialState);
});

describe('adminStore', () => {
  it('TC-01: login sets tenantId and isLoggedIn', () => {
    useAdminStore.getState().login('tenant-001');
    const s = useAdminStore.getState();
    expect(s.tenantId).toBe('tenant-001');
    expect(s.isLoggedIn).toBe(true);
  });

  it('TC-02: logout resets state', () => {
    useAdminStore.getState().login('tenant-001');
    useAdminStore.getState().logout();
    const s = useAdminStore.getState();
    expect(s.tenantId).toBeNull();
    expect(s.isLoggedIn).toBe(false);
  });

  it('TC-03: setActiveTab changes tab', () => {
    useAdminStore.getState().setActiveTab('dashboard');
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
  });

  it('TC-04: default activeTab is notifications', () => {
    expect(useAdminStore.getState().activeTab).toBe('notifications');
  });
});
