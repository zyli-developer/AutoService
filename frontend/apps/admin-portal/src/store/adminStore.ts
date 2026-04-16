import { create } from 'zustand';

export interface Notification {
  id: string;
  type: 'alert' | 'info' | 'command';
  title: string;
  description: string;
  ts: string;
}

export interface AdminState {
  tenantId: string | null;
  isLoggedIn: boolean;
  activeTab: 'wizard' | 'dashboard' | 'notifications' | 'proposals';
  notifications: Notification[];

  login: (tenantId: string) => void;
  logout: () => void;
  setActiveTab: (tab: AdminState['activeTab']) => void;
  addNotification: (n: Notification) => void;
  clearNotifications: () => void;
}

export const initialState = {
  tenantId: null,
  isLoggedIn: false,
  activeTab: 'wizard' as const,
  notifications: [] as Notification[],
};

export const useAdminStore = create<AdminState>((set) => ({
  ...initialState,

  login: (tenantId) => set({ tenantId, isLoggedIn: true }),

  logout: () => set({ ...initialState }),

  setActiveTab: (activeTab) => set({ activeTab }),

  addNotification: (n) => set((state) => ({ notifications: [...state.notifications, n] })),

  clearNotifications: () => set({ notifications: [] }),
}));
