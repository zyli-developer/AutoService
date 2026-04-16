import { create } from 'zustand';

export type CardStatus =
  | 'idle'
  | 'waiting-reply'
  | 'escalation-pending'
  | 'human-takeover'
  | 'closed';

export interface Conversation {
  id: string;
  squadId: string;
  customerId: string;
  mode: 'auto' | 'copilot' | 'takeover';
  state: 'created' | 'active' | 'idle' | 'closed';
  lastMessage: string;
  lastMessageSender: 'customer' | 'agent' | '';
  lastActivityTs: string;
}

export function deriveCardStatus(conv: Conversation): CardStatus {
  if (conv.state === 'closed') return 'closed';
  if (conv.mode === 'takeover') return 'human-takeover';
  if (conv.mode === 'copilot') return 'escalation-pending';
  if (conv.lastMessageSender === 'customer') return 'waiting-reply';
  return 'idle';
}

export interface OperatorState {
  operatorId: string | null;
  token: string | null;
  isLoggedIn: boolean;
  wsStatus: 'idle' | 'connecting' | 'open' | 'closed';
  sessionId: string | null;
  squads: string[];
  activeSquadId: string | null;
  subscriptions: Record<string, string>;
  conversations: Record<string, Conversation>;

  login: (operatorId: string, token: string) => void;
  logout: () => void;
  setWsStatus: (s: OperatorState['wsStatus']) => void;
  setSessionId: (id: string) => void;
  addSquad: (squadId: string) => void;
  setActiveSquad: (squadId: string) => void;
  addSubscription: (squadId: string, subscriptionId: string) => void;
  addConversation: (conv: Conversation) => void;
  updateConversation: (id: string, patch: Partial<Conversation>) => void;
  removeConversation: (id: string) => void;
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
  conversations: {} as Record<string, Conversation>,
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

  addConversation: (conv) =>
    set((state) => ({
      conversations: { ...state.conversations, [conv.id]: conv },
    })),

  updateConversation: (id, patch) =>
    set((state) => {
      const existing = state.conversations[id];
      if (!existing) return state;
      return {
        conversations: { ...state.conversations, [id]: { ...existing, ...patch } },
      };
    }),

  removeConversation: (id) =>
    set((state) => {
      const { [id]: _, ...rest } = state.conversations;
      return { conversations: rest };
    }),
}));
