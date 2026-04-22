import { describe, it, expect, beforeEach } from 'vitest';
import { useAdminStore, initialState } from '../store/adminStore';

beforeEach(() => {
  useAdminStore.setState(initialState);
});

describe('adminStore', () => {
  it('TC-02: logout resets tenantId', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'tenant-001' });
    useAdminStore.getState().logout();
    expect(useAdminStore.getState().tenantId).toBeNull();
  });

  it('TC-03: setActiveTab changes tab', () => {
    useAdminStore.getState().setActiveTab('dashboard');
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
  });

  it('TC-04: default activeTab is notifications', () => {
    expect(useAdminStore.getState().activeTab).toBe('notifications');
  });

  it('TC-05: setTenantId updates tenantId', () => {
    useAdminStore.getState().setTenantId('acme');
    expect(useAdminStore.getState().tenantId).toBe('acme');
  });

  it('TC-06: setTenantId(null) clears tenantId', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'acme' });
    useAdminStore.getState().setTenantId(null);
    expect(useAdminStore.getState().tenantId).toBeNull();
  });
});
