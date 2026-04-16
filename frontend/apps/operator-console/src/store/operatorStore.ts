import { create } from 'zustand';

export interface OperatorState {
  operatorId: string | null;
  token: string | null;
  isLoggedIn: boolean;
  wsStatus: 'idle' | 'connecting' | 'open' | 'closed';
  sessionId: string | null;
  squads: string[];
  activeSquadId: string | null;
  subscriptions: Record<string, string>;

  login: (operatorId: string, token: string) => void;
  logout: () => void;
  setWsStatus: (s: OperatorState['wsStatus']) => void;
  setSessionId: (id: string) => void;
  addSquad: (squadId: string) => void;
  setActiveSquad: (squadId: string) => void;
  addSubscription: (squadId: string, subscriptionId: string) => void;
}

export const initialState = {
  operatorId: null,
  token: null,
  isLoggedIn: false,
  wsStatus: 'idle' as const,
  sessionId: null,
  squads: [],
  activeSquadId: null,
  subscriptions: {},
};

export const useOperatorStore = create<OperatorState>((set) => ({
  ...initialState,

  login: (operatorId, token) =>
    set({ operatorId, token, isLoggedIn: true }),

  logout: () =>
    set({ ...initialState }),

  setWsStatus: (wsStatus) => set({ wsStatus }),

  setSessionId: (sessionId) => set({ sessionId }),

  addSquad: (squadId) =>
    set((state) => {
      if (state.squads.includes(squadId)) return state;
      const squads = [...state.squads, squadId];
      return { squads, activeSquadId: state.activeSquadId ?? squadId };
    }),

  setActiveSquad: (activeSquadId) => set({ activeSquadId }),

  addSubscription: (squadId, subscriptionId) =>
    set((state) => ({
      subscriptions: { ...state.subscriptions, [squadId]: subscriptionId },
    })),
}));
