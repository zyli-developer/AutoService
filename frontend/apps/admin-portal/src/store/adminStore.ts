import { create } from 'zustand';
import { persist } from 'zustand/middleware';

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

export interface ProposalUI {
  id: string;
  created_at: string;
  category: 'response_quality' | 'workflow' | 'knowledge_gap' | 'tone';
  title: string;
  description: string;
  suggestion: string;
  priority: 'high' | 'medium' | 'low';
  status: 'draft' | 'accepted' | 'rejected' | 'implemented';
  source_conversations: string[];
  evidence: string[];
  compliance_check: { passed: boolean; flags: string[] };
}

export type CanaryStage = 'disabled' | 'stage_5' | 'stage_25' | 'stage_100';

export interface CanaryMetricUI {
  name: string;
  baseline: number;
  current: number;
  breached: boolean;
}

export interface CanaryStateUI {
  stage: CanaryStage;
  percentage: number;
  metrics: CanaryMetricUI[];
  autoRollback: boolean;
  rolledBack: boolean;
}

export interface AdminState {
  tenantId: string | null;
  isLoggedIn: boolean;
  // T6F.5 — widened to include tenant-variant `'chat'` key (spec §4.2).
  // Master variant continues to use 'notifications'/'dashboard'/'wizard'/
  // 'proposals'/'billing'; tenant variant adds 'chat'. The union is honest
  // so AdminRail variant switching no longer needs a cast at the call site.
  activeTab: 'wizard' | 'dashboard' | 'notifications' | 'proposals' | 'dream' | 'billing' | 'chat';
  notifications: Notification[];

  wizardStep: number;
  wizardFormData: WizardFormData;
  generating: boolean;
  generationResult: GenerationResult | null;

  rehearsalDialogs: SimDialogUI[];
  rehearsalLoading: boolean;

  proposals: ProposalUI[];
  proposalsLoading: boolean;

  canaryState: CanaryStateUI | null;

  login: (tenantId: string) => void;
  setTenantId: (tenantId: string | null) => void;
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

  setProposals: (proposals: ProposalUI[]) => void;
  setProposalsLoading: (v: boolean) => void;
  updateProposalStatus: (proposalId: string, status: ProposalUI['status']) => void;

  setCanaryState: (state: CanaryStateUI | null) => void;
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
  activeTab: 'notifications' as const,
  notifications: [] as Notification[],
  wizardStep: 0,
  wizardFormData: initialWizardFormData,
  generating: false,
  generationResult: null as GenerationResult | null,
  rehearsalDialogs: [] as SimDialogUI[],
  rehearsalLoading: false,
  proposals: [] as ProposalUI[],
  proposalsLoading: false,
  canaryState: null as CanaryStateUI | null,
};

export const useAdminStore = create<AdminState>()(
  persist(
    (set) => ({
      ...initialState,

      login: (tenantId) => set({ tenantId, isLoggedIn: true }),
      setTenantId: (tenantId) => set({ tenantId }),

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

      setProposals: (proposals) => set({ proposals }),
      setProposalsLoading: (proposalsLoading) => set({ proposalsLoading }),
      updateProposalStatus: (proposalId, status) =>
        set((state) => ({
          proposals: state.proposals.map((p) =>
            p.id === proposalId ? { ...p, status } : p
          ),
        })),

      setCanaryState: (canaryState) => set({ canaryState }),
    }),
    {
      name: 'admin-wizard-state',
      partialize: (state) => ({
        wizardStep: state.wizardStep,
        generationResult: state.generationResult,
      }),
    },
  ),
);
