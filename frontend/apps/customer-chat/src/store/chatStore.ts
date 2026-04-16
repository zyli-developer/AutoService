import { create } from 'zustand';

export interface ChatMessage {
  id: string;
  source: string;
  sourceRole: 'customer' | 'agent' | 'operator' | 'system' | undefined;
  content: string;
  visibility: 'public' | 'side' | 'system';
  timestamp: string;
  sequenceNumber: number;
  status: 'sending' | 'sent' | 'failed';
  clientMsgId?: string;
  senderName?: string;       // from source_display.name
  avatarUrl?: string;        // from source_display.avatar_url
  metadata?: {
    attachment_url?: string;
    [key: string]: unknown;
  };
  contentType?: 'text' | 'image';  // derived: 'image' if attachment_url exists
}

interface ChatState {
  connectionStatus: 'idle' | 'connecting' | 'open' | 'closed';
  sessionId: string | null;
  conversationId: string | null;
  messages: ChatMessage[];
  isAgentTyping: boolean;
  // Actions
  addMessage: (msg: ChatMessage) => void;
  updateMessage: (messageId: string, content: string) => void;
  confirmOptimistic: (clientMsgId: string, serverMsg: Partial<ChatMessage>) => void;
  setConnectionStatus: (status: ChatState['connectionStatus']) => void;
  setSessionId: (id: string) => void;
  setConversationId: (id: string) => void;
  setAgentTyping: (v: boolean) => void;
}

export const initialState: Omit<
  ChatState,
  'addMessage' | 'updateMessage' | 'confirmOptimistic' | 'setConnectionStatus' | 'setSessionId' | 'setConversationId' | 'setAgentTyping'
> = {
  connectionStatus: 'idle',
  sessionId: null,
  conversationId: null,
  messages: [],
  isAgentTyping: false,
};

export const useChatStore = create<ChatState>()((set) => ({
  ...initialState,

  addMessage: (msg) =>
    set((state) => ({
      messages: [...state.messages, msg],
      isAgentTyping:
        msg.sourceRole === 'agent' || msg.sourceRole === 'operator'
          ? false
          : state.isAgentTyping,
    })),

  updateMessage: (messageId, content) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, content } : m,
      ),
    })),

  confirmOptimistic: (clientMsgId, serverMsg) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.clientMsgId === clientMsgId
          ? { ...m, ...serverMsg, status: 'sent' as const }
          : m,
      ),
    })),

  setConnectionStatus: (status) => set({ connectionStatus: status }),

  setSessionId: (id) => set({ sessionId: id }),

  setConversationId: (id) => set({ conversationId: id }),

  setAgentTyping: (v) => set({ isAgentTyping: v }),
}));
