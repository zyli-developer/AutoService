import { create } from 'zustand';

export interface TakeoverWarning {
  remainingMs: number;
  reason: 'idle';
  warningFrameId: string;
  armedAt: string;
}

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
  takeoverOperatorId?: string | null;
  takeoverWarning?: TakeoverWarning;
  takeoverArmedAt?: string;     // ISO timestamp from backend
  takeoverIdleMs?: number;
  takeoverWarningMs?: number;
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
  updateCopilotMessage: (convId: string, messageId: string, patch: Partial<CopilotMessage>) => void;
  setTakeoverWarning: (conversationId: string, w: TakeoverWarning) => void;
  clearTakeoverWarning: (conversationId: string) => void;
  setTakeoverArmed: (conversationId: string, armed: { armedAt: string; idleMs: number; warningMs: number }) => void;
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

  openCopilot: (convId) => set(() => ({
    activeCopilotConvId: convId,
  })),

  closeCopilot: () => set({ activeCopilotConvId: null }),

  addCopilotMessage: (convId, msg) =>
    set((state) => {
      const existing = state.copilotMessages[convId] ?? [];
      if (existing.some((m) => m.id === msg.id)) return state;
      return {
        copilotMessages: {
          ...state.copilotMessages,
          [convId]: [...existing, msg],
        },
      };
    }),

  updateCopilotMessage: (convId, messageId, patch) =>
    set((state) => {
      const existing = state.copilotMessages[convId];
      if (!existing) return state;
      const idx = existing.findIndex((m) => m.id === messageId);
      if (idx < 0) return state;
      const next = [...existing];
      next[idx] = { ...next[idx], ...patch };
      return {
        copilotMessages: { ...state.copilotMessages, [convId]: next },
      };
    }),

  setTakeoverWarning: (id, warning) => set((state) => {
    const conv = state.conversations[id];
    if (!conv) return state;
    return {
      conversations: {
        ...state.conversations,
        [id]: { ...conv, takeoverWarning: warning },
      },
    };
  }),

  clearTakeoverWarning: (id) => set((state) => {
    const conv = state.conversations[id];
    if (!conv || !conv.takeoverWarning) return state;
    const copy: Conversation = { ...conv };
    delete (copy as any).takeoverWarning;
    return {
      conversations: { ...state.conversations, [id]: copy },
    };
  }),

  setTakeoverArmed: (id, { armedAt, idleMs, warningMs }) => set((state) => {
    const conv = state.conversations[id];
    if (!conv) return state;
    return {
      conversations: {
        ...state.conversations,
        [id]: {
          ...conv,
          takeoverArmedAt: armedAt,
          takeoverIdleMs: idleMs,
          takeoverWarningMs: warningMs,
        },
      },
    };
  }),
}));
