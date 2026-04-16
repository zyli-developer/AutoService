import { create } from 'zustand';

export interface AdminState {
  tenantId: string | null;
  isLoggedIn: boolean;
  activeTab: 'wizard' | 'dashboard' | 'notifications' | 'proposals';

  login: (tenantId: string) => void;
  logout: () => void;
  setActiveTab: (tab: AdminState['activeTab']) => void;
}

export const initialState = {
  tenantId: null,
  isLoggedIn: false,
  activeTab: 'wizard' as const,
};

export const useAdminStore = create<AdminState>((set) => ({
  ...initialState,

  login: (tenantId) => set({ tenantId, isLoggedIn: true }),

  logout: () => set({ ...initialState }),

  setActiveTab: (activeTab) => set({ activeTab }),
}));
