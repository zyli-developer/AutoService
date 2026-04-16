import { create } from 'zustand';

export interface Notification {
  id: string;
  type: 'alert' | 'info' | 'command';
  title: string;
  description: string;
  ts: string;
}

export interface SoulDraft {
  role: string;
  kbHitCount: number;
  mode: 'ai' | 'template_fallback';
  warnings: string[];
}

export interface GenerationResult {
  tenantId: string;
  souls: Record<string, SoulDraft>;
  totalKbHits: number;
  mode: 'ai' | 'template_fallback';
  warnings: string[];
}

export interface WizardFormData {
  brandName: string;
  websiteUrl: string;
  industry: string;
  languages: string[];
  extraContext: string;
  files: File[];
}

export interface SimTurnUI {
  role: 'customer' | 'agent';
  content: string;
  metadata: Record<string, unknown>;
}

export interface SimDialogUI {
  id: string;
  scenario: {
    id: string;
    name_zh: string;
    intent: string;
    keywords: string[];
    trap_question: string;
    degraded: boolean;
  };
  persona: {
    id: string;
    name_zh: string;
    traits: string[];
    communication_style: string;
  };
  turns: SimTurnUI[];
  language: string;
  review_status: 'pending' | 'approved' | 'flagged';
}

export interface AdminState {
  tenantId: string | null;
  isLoggedIn: boolean;
  activeTab: 'wizard' | 'dashboard' | 'notifications' | 'proposals';
  notifications: Notification[];

  wizardStep: number;
  wizardFormData: WizardFormData;
  generating: boolean;
  generationResult: GenerationResult | null;

  rehearsalDialogs: SimDialogUI[];
  rehearsalLoading: boolean;

  login: (tenantId: string) => void;
  logout: () => void;
  setActiveTab: (tab: AdminState['activeTab']) => void;
  addNotification: (n: Notification) => void;
  clearNotifications: () => void;

  setWizardStep: (step: number) => void;
  setWizardFormData: (data: Partial<WizardFormData>) => void;
  setGenerating: (v: boolean) => void;
  setGenerationResult: (r: GenerationResult | null) => void;

  setRehearsalDialogs: (dialogs: SimDialogUI[]) => void;
  setRehearsalLoading: (v: boolean) => void;
  updateDialogReviewStatus: (dialogId: string, status: SimDialogUI['review_status']) => void;
}

const initialWizardFormData: WizardFormData = {
  brandName: '',
  websiteUrl: '',
  industry: 'general',
  languages: ['zh', 'en'],
  extraContext: '',
  files: [],
};

export const initialState = {
  tenantId: null,
  isLoggedIn: false,
  activeTab: 'wizard' as const,
  notifications: [] as Notification[],
  wizardStep: 0,
  wizardFormData: initialWizardFormData,
  generating: false,
  generationResult: null as GenerationResult | null,
  rehearsalDialogs: [] as SimDialogUI[],
  rehearsalLoading: false,
};

export const useAdminStore = create<AdminState>((set) => ({
  ...initialState,

  login: (tenantId) => set({ tenantId, isLoggedIn: true }),

  logout: () => set({ ...initialState }),

  setActiveTab: (activeTab) => set({ activeTab }),

  addNotification: (n) => set((state) => ({ notifications: [...state.notifications, n] })),

  clearNotifications: () => set({ notifications: [] }),

  setWizardStep: (wizardStep) => set({ wizardStep }),

  setWizardFormData: (data) =>
    set((state) => ({ wizardFormData: { ...state.wizardFormData, ...data } })),

  setGenerating: (generating) => set({ generating }),

  setGenerationResult: (generationResult) => set({ generationResult }),

  setRehearsalDialogs: (rehearsalDialogs) => set({ rehearsalDialogs }),
  setRehearsalLoading: (rehearsalLoading) => set({ rehearsalLoading }),
  updateDialogReviewStatus: (dialogId, status) =>
    set((state) => ({
      rehearsalDialogs: state.rehearsalDialogs.map((d) =>
        d.id === dialogId ? { ...d, review_status: status } : d
      ),
    })),
}));
