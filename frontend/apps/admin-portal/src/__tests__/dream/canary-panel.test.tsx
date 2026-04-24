import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CanaryPanel } from '../../components/dream/canary-panel';

const ACCEPTED_PROPOSAL = {
  id: 'prop_accepted',
  created_at: '2026-04-22T10:00:00Z',
  category: 'response_quality',
  title: 'Improve refund tone',
  priority: 'high',
  status: 'accepted' as const,
  suggestion: 'soften refund replies',
};

const DRAFT_PROPOSAL = { ...ACCEPTED_PROPOSAL, id: 'prop_draft', status: 'draft' as const };
const REJECTED_PROPOSAL = { ...ACCEPTED_PROPOSAL, id: 'prop_rej', status: 'rejected' as const };
const APPLIED_PROPOSAL = { ...ACCEPTED_PROPOSAL, id: 'prop_app', status: 'applied' as const };

const CANARY_WATCHING = {
  stage: 1,
  percentage: 5,
  can_advance: true,
  history: [],
  monitor: { status: 'watching' as const },
};

const CANARY_WITH_BREACHES = {
  stage: 2,
  percentage: 25,
  can_advance: false,
  history: [],
  monitor: {
    status: 'breached' as const,
    breaches: [
      { metric: 'accept_wait_ms', baseline: 200, current: 420 },
      { metric: 'csat', baseline: 4.5, current: 3.9 },
    ],
  },
};

vi.mock('@autoservice/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string>) =>
      params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}));

const fetchJSONMock = vi.fn();
const postJSONMock = vi.fn();

vi.mock('../../api', () => ({
  fetchJSON: (path: string) => fetchJSONMock(path),
  postJSON: (path: string, body?: unknown) => postJSONMock(path, body),
  postForm: vi.fn(() => Promise.resolve({})),
}));

function primeMocks(canary = CANARY_WATCHING) {
  fetchJSONMock.mockImplementation((path: string) => {
    if (path.startsWith('/api/canary/status')) return Promise.resolve(canary);
    return Promise.resolve({});
  });
  postJSONMock.mockResolvedValue({ ok: true });
}

describe('CanaryPanel — 3-button pattern (T5S.12 D2/U4)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders panel with proposal title and 3-button row', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel')).toBeInTheDocument();
    expect(screen.getByTestId('canary-panel-title')).toHaveTextContent('Improve refund tone');
    expect(screen.getByTestId('canary-panel-reject-btn')).toBeInTheDocument();
    expect(screen.getByTestId('canary-panel-approve-btn')).toBeInTheDocument();
    expect(screen.getByTestId('canary-panel-apply-btn')).toBeInTheDocument();
  });

  it('Apply button ENABLED exactly when proposal.status === "accepted"', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-apply-btn')).not.toBeDisabled();
  });

  it('Apply button DISABLED when proposal.status === "draft"', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-apply-btn')).toBeDisabled();
  });

  it('Apply button DISABLED when proposal.status === "rejected"', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={REJECTED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-apply-btn')).toBeDisabled();
  });

  it('Apply button DISABLED when proposal.status === "applied"', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={APPLIED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-apply-btn')).toBeDisabled();
  });

  it('Apply button shows tooltip explaining why it is disabled', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={() => {}} />);
    });
    const btn = screen.getByTestId('canary-panel-apply-btn');
    expect(btn.getAttribute('title')).toMatch(/requires_accepted|admin\.dream\.apply/);
  });

  it('Apply click POSTs ONLY to /api/admin/proposals/{id}/apply (CON-04 single write path)', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await user.click(screen.getByTestId('canary-panel-apply-btn'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith(
        '/api/admin/proposals/prop_accepted/apply',
        undefined,
      );
    });
    // CON-04 red line: Apply must NEVER call any other status-mutating endpoint.
    const callsToOtherMutators = postJSONMock.mock.calls.filter(
      ([path]) =>
        typeof path === 'string' &&
        (path.includes('/proposals/run') ||
          path.endsWith('/accept') ||
          path.endsWith('/reject') ||
          path.startsWith('/api/management/chat')),
    );
    expect(callsToOtherMutators).toEqual([]);
  });

  it('Approve click POSTs /api/management/chat-legacy?message=/approve <id> (M1 slash dispatcher)', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={() => {}} />);
    });
    await user.click(screen.getByTestId('canary-panel-approve-btn'));
    await waitFor(() => {
      // chat-legacy takes message as a *query-string* arg (api_routes.py
      // :1291-1371), not a JSON body; chat (without -legacy) is the M2
      // _master LLM pass-through and doesn't dispatch slash commands.
      // postJSON is called single-arg, but our mock adapter forwards
      // (path, body?) so body === undefined here.
      expect(postJSONMock).toHaveBeenCalledWith(
        `/api/management/chat-legacy?message=${encodeURIComponent('/approve prop_draft')}`,
        undefined,
      );
    });
    // Guard against regression onto the M2 endpoint.
    const callsToWrongEndpoint = postJSONMock.mock.calls.filter(
      ([path]) =>
        typeof path === 'string' &&
        path.startsWith('/api/management/chat') &&
        !path.startsWith('/api/management/chat-legacy'),
    );
    expect(callsToWrongEndpoint).toEqual([]);
  });

  it('Reject click POSTs /api/management/chat-legacy?message=/reject <id> (M1 slash dispatcher)', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={() => {}} />);
    });
    await user.click(screen.getByTestId('canary-panel-reject-btn'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith(
        `/api/management/chat-legacy?message=${encodeURIComponent('/reject prop_draft')}`,
        undefined,
      );
    });
  });

  it('Approve and Reject DISABLED when proposal.status is terminal (applied / rejected)', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={APPLIED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-approve-btn')).toBeDisabled();
    expect(screen.getByTestId('canary-panel-reject-btn')).toBeDisabled();
  });

  it('Approve DISABLED when already accepted (idempotent guard)', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    expect(screen.getByTestId('canary-panel-approve-btn')).toBeDisabled();
  });

  it('embeds CanaryProgress (progress bar + stages 0/5/25/100)', async () => {
    primeMocks();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    // CanaryProgress self-renders after fetch; wait for it.
    await waitFor(() =>
      expect(screen.getByTestId('canary-progress')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('canary-steps')).toBeInTheDocument();
  });

  it('renders MetricCompare when breaches present', async () => {
    primeMocks(CANARY_WITH_BREACHES);
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('metric-compare')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('metric-compare-row-accept_wait_ms')).toBeInTheDocument();
    expect(screen.getByTestId('metric-compare-row-csat')).toBeInTheDocument();
  });

  it('hides MetricCompare when monitor clean (no breaches)', async () => {
    primeMocks(CANARY_WATCHING);
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    // wait until the canary fetch resolves so MetricCompare has data to decide on
    await waitFor(() =>
      expect(screen.getByTestId('canary-progress')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('metric-compare')).not.toBeInTheDocument();
  });

  it('calls onReload after successful Apply', async () => {
    primeMocks();
    const user = userEvent.setup();
    const onReload = vi.fn();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={onReload} />);
    });
    await user.click(screen.getByTestId('canary-panel-apply-btn'));
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });

  it('calls onReload after successful Approve', async () => {
    primeMocks();
    const user = userEvent.setup();
    const onReload = vi.fn();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={onReload} />);
    });
    await user.click(screen.getByTestId('canary-panel-approve-btn'));
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });

  it('calls onReload after successful Reject', async () => {
    primeMocks();
    const user = userEvent.setup();
    const onReload = vi.fn();
    await act(async () => {
      render(<CanaryPanel proposal={DRAFT_PROPOSAL} onReload={onReload} />);
    });
    await user.click(screen.getByTestId('canary-panel-reject-btn'));
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });
});

describe('CanaryPanel — Advance / Rollback (plan §Scope §2)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('Advance button POSTs /api/canary/advance after confirm', async () => {
    primeMocks(CANARY_WATCHING);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('canary-panel-advance-btn')).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId('canary-panel-advance-btn'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith('/api/canary/advance', undefined);
    });
    expect(confirmSpy).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('Advance is a no-op when confirm is cancelled', async () => {
    primeMocks(CANARY_WATCHING);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('canary-panel-advance-btn')).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId('canary-panel-advance-btn'));
    // confirm was prompted; no POST /api/canary/advance fired.
    expect(confirmSpy).toHaveBeenCalled();
    const advanceCalls = postJSONMock.mock.calls.filter(
      ([p]) => p === '/api/canary/advance',
    );
    expect(advanceCalls).toEqual([]);
    confirmSpy.mockRestore();
  });

  it('Rollback button POSTs /api/canary/rollback after confirm', async () => {
    primeMocks(CANARY_WITH_BREACHES);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('canary-panel-rollback-btn')).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId('canary-panel-rollback-btn'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith('/api/canary/rollback', undefined);
    });
    confirmSpy.mockRestore();
  });

  it('Advance DISABLED when percentage === 100 (already at full rollout)', async () => {
    primeMocks({
      stage: 3,
      percentage: 100,
      can_advance: false,
      history: [],
      monitor: { status: 'healthy' },
    });
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('canary-panel-advance-btn')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('canary-panel-advance-btn')).toBeDisabled();
  });

  it('Rollback DISABLED when percentage === 0 (nothing to roll back)', async () => {
    primeMocks({
      stage: 0,
      percentage: 0,
      can_advance: true,
      history: [],
      monitor: { status: 'idle' },
    });
    await act(async () => {
      render(<CanaryPanel proposal={ACCEPTED_PROPOSAL} onReload={() => {}} />);
    });
    await waitFor(() =>
      expect(screen.getByTestId('canary-panel-rollback-btn')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('canary-panel-rollback-btn')).toBeDisabled();
  });
});
