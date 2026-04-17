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

export interface CopilotMessage {
  id: string;
  text: string;
  sender: 'operator' | 'agent' | 'customer';
  ts: string;
  visibility?: 'public' | 'side' | 'system';
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
  concurrencyLimit: number;
  unreadCounts: Record<string, number>;
  activeCopilotConvId: string | null;
  copilotMessages: Record<string, CopilotMessage[]>;

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
  setConcurrencyLimit: (n: number) => void;
  incrementUnread: (squadId: string) => void;
  clearUnread: (squadId: string) => void;
  openCopilot: (convId: string) => void;
  closeCopilot: () => void;
  addCopilotMessage: (convId: string, msg: CopilotMessage) => void;
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
  concurrencyLimit: 5,
  unreadCounts: {} as Record<string, number>,
  activeCopilotConvId: null,
  copilotMessages: {} as Record<string, CopilotMessage[]>,
};

export const useOperatorStore = create<OperatorState>((set) => ({
  ...initialState,

  login: (operatorId, token) =>
    set({ operatorId, token, isLoggedIn: true, squads: ['web-support'], activeSquadId: 'web-support' }),

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

  setConcurrencyLimit: (n) => set({ concurrencyLimit: n }),

  incrementUnread: (squadId) =>
    set((state) => ({
      unreadCounts: {
        ...state.unreadCounts,
        [squadId]: (state.unreadCounts[squadId] ?? 0) + 1,
      },
    })),

  clearUnread: (squadId) =>
    set((state) => ({
      unreadCounts: { ...state.unreadCounts, [squadId]: 0 },
    })),

  openCopilot: (convId) => set((state) => ({
    activeCopilotConvId: convId,
    copilotMessages: { ...state.copilotMessages, [convId]: [] },
  })),

  closeCopilot: () => set({ activeCopilotConvId: null }),

  addCopilotMessage: (convId, msg) =>
    set((state) => {
      const existing = state.copilotMessages[convId] ?? [];
      // Dedup by id OR by same sender+text within 5 seconds
      if (existing.some((m) => m.id === msg.id)) return state;
      if (existing.some((m) =>
        m.sender === msg.sender && m.text === msg.text &&
        Math.abs(new Date(m.ts).getTime() - new Date(msg.ts).getTime()) < 5000
      )) return state;
      return {
        copilotMessages: {
          ...state.copilotMessages,
          [convId]: [...existing, msg],
        },
      };
    }),
}));
