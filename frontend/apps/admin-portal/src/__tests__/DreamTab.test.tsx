import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DreamTab } from '../components/DreamTab';

const MOCK_STATUS = {
  tenant_id: 'acme',
  running: false,
  reason_code: 'idle',
  last_run_summary: {
    run_id: 'run_abc',
    started_at: '2026-04-21T10:00:00Z',
    ended_at: '2026-04-21T10:01:00Z',
    status: 'completed',
    proposals_emitted: 2,
    tool_calls: 3,
  },
  next_eligible_at: '2026-04-21T11:00:00Z',
};

const MOCK_PROPOSALS = [
  { id: 'prop_a', created_at: '2026-04-21', category: 'platform_level', title: 'Increase pool size', priority: 'high', status: 'accepted', suggestion: 'bump cc_pool capacity to 8' },
  { id: 'prop_b', created_at: '2026-04-20', category: 'response_quality', title: 'Tone improvement', priority: 'medium', status: 'draft', suggestion: 'soften refund replies' },
  { id: 'prop_c', created_at: '2026-04-18', category: 'workflow', title: 'Already applied change', priority: 'low', status: 'applied' },
  { id: 'prop_d', created_at: '2026-04-15', category: 'workflow', title: 'Rejected change', priority: 'low', status: 'rejected' },
];

const MOCK_RUNS = [
  { id: 'run_abc', tenant_id: 'acme', started_at: '2026-04-21T10:00:00Z', ended_at: '2026-04-21T10:01:00Z', status: 'completed', tokens_in: 500, tokens_out: 200, error: null },
];

vi.mock('@autoservice/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string>) =>
      params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}));

vi.mock('../store/adminStore', () => ({
  useAdminStore: (selector: (s: { tenantId: string }) => unknown) =>
    selector({ tenantId: 'acme' }),
}));

const fetchJSONMock = vi.fn();
const postJSONMock = vi.fn();

vi.mock('../api', () => ({
  fetchJSON: (path: string) => fetchJSONMock(path),
  postJSON: (path: string, body?: unknown) => postJSONMock(path, body),
  postForm: vi.fn(() => Promise.resolve({})),
}));

const MOCK_TENANTS = [
  { tenant_id: '_master', name: 'Platform master', status: 'sandbox' },
  { tenant_id: 'acme', name: 'Acme Corp', status: 'sandbox' },
  { tenant_id: 'mystore', name: 'My Store', status: 'sandbox' },
];

function primeMocks() {
  fetchJSONMock.mockImplementation((path: string) => {
    if (path.startsWith('/api/master/tenants')) return Promise.resolve(MOCK_TENANTS);
    if (path.startsWith('/api/dream/status')) return Promise.resolve(MOCK_STATUS);
    if (path.startsWith('/api/proposals')) return Promise.resolve(MOCK_PROPOSALS);
    if (path.startsWith('/api/dream/runs'))
      return Promise.resolve({ tenant_id: 'acme', runs: MOCK_RUNS });
    return Promise.resolve({});
  });
  postJSONMock.mockResolvedValue({ ok: true });
}

describe('DreamTab', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders status card + proposals + runs on load', async () => {
    primeMocks();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-status-card')).toBeInTheDocument());
    expect(screen.getByTestId('dream-status-running')).toHaveTextContent(
      'admin.dream.status.running_no'
    );
    expect(screen.getByTestId('dream-reason-code')).toHaveTextContent('idle');
    expect(screen.getByTestId('dream-proposals-section')).toBeInTheDocument();
    expect(screen.getByTestId('dream-runs-section')).toBeInTheDocument();
  });

  it('filters pending = draft + accepted (excludes rejected and applied)', async () => {
    primeMocks();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-proposals-table')).toBeInTheDocument());
    // prop_a (accepted) + prop_b (draft) = 2; prop_c (applied) and prop_d (rejected) excluded
    expect(screen.getByTestId('dream-apply-prop_a')).toBeInTheDocument();
    expect(screen.getByTestId('dream-apply-prop_b')).toBeInTheDocument();
    expect(screen.queryByTestId('dream-apply-prop_c')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dream-apply-prop_d')).not.toBeInTheDocument();
  });

  it('applied proposals shown in "recently applied" section', async () => {
    primeMocks();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-applied-section')).toBeInTheDocument());
    expect(screen.getByTestId('dream-applied-section')).toHaveTextContent('Already applied change');
  });

  it('Apply button disabled for status=draft (requires accepted)', async () => {
    primeMocks();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-apply-prop_b')).toBeInTheDocument());
    expect(screen.getByTestId('dream-apply-prop_b')).toBeDisabled();
    expect(screen.getByTestId('dream-apply-prop_a')).not.toBeDisabled();
  });

  it('clicking Apply posts to /api/admin/proposals/{id}/apply', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-apply-prop_a')).toBeInTheDocument());
    await user.click(screen.getByTestId('dream-apply-prop_a'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith('/api/admin/proposals/prop_a/apply', undefined);
    });
  });

  it('Trigger button posts to /api/dream/trigger with tenant_id', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-trigger-btn')).toBeInTheDocument());
    await user.click(screen.getByTestId('dream-trigger-btn'));
    await waitFor(() => {
      expect(postJSONMock).toHaveBeenCalledWith('/api/dream/trigger', { tenant_id: 'acme' });
    });
  });

  it('tenant selector shows all loaded tenants and defaults to store tenant when valid', async () => {
    primeMocks();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-tenant-select')).toBeInTheDocument());
    const select = screen.getByTestId('dream-tenant-select') as HTMLSelectElement;
    // store tenantId is 'acme' and 'acme' is in MOCK_TENANTS → preselected
    expect(select.value).toBe('acme');
    // All 3 options available
    expect(select.querySelectorAll('option').length).toBe(3);
  });

  it('tenant selector change triggers fresh data load for new tenant', async () => {
    primeMocks();
    const user = userEvent.setup();
    await act(async () => {
      render(<DreamTab />);
    });
    await waitFor(() => expect(screen.getByTestId('dream-tenant-select')).toBeInTheDocument());
    fetchJSONMock.mockClear();
    await user.selectOptions(screen.getByTestId('dream-tenant-select'), 'mystore');
    await waitFor(() => {
      const calls = fetchJSONMock.mock.calls.map((c) => c[0] as string);
      expect(calls.some((p) => p.includes('tenant_id=mystore'))).toBe(true);
    });
  });
});
