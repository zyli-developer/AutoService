import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { useAdminStore } from '../store/adminStore';

// Mock API — postJSON rejects by default so component falls back to local
// mockGenerate on /rehearsal/generate. Individual tests override the mock to
// exercise the /rehearsal/review happy path (T1F.7).
const postJSONMock = vi.fn<[string, unknown?], Promise<unknown>>(() =>
  Promise.reject(new Error('not mocked')),
);
vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.reject(new Error('not mocked'))),
  postJSON: (path: string, body?: unknown) => postJSONMock(path, body),
  postForm: vi.fn(() => Promise.reject(new Error('not mocked'))),
}));

import { VirtualRehearsalStep } from '../components/wizard/VirtualRehearsalStep';

describe('VirtualRehearsalStep', () => {
  beforeEach(() => {
    useAdminStore.setState({
      rehearsalDialogs: [],
      rehearsalLoading: false,
    });
    postJSONMock.mockReset();
    postJSONMock.mockImplementation(() => Promise.reject(new Error('not mocked')));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: renders page with title and start button', () => {
    render(<VirtualRehearsalStep tenantId="test-tenant" />);
    expect(screen.getByTestId('virtual-rehearsal-step')).toBeInTheDocument();
    expect(screen.getByTestId('btn-start-rehearsal')).toBeInTheDocument();
  });

  it('TC-002: start rehearsal shows loading then dialog cards', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });

    expect(screen.getByTestId('rehearsal-loading')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByTestId('dialog-list')).toBeInTheDocument();
    const cards = screen.getAllByTestId(/^dialog-card-/);
    expect(cards.length).toBe(12);
  });

  it('TC-003: dialog card shows scenario + persona info', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getAllByText(/通用问候/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/愤怒退款客户/).length).toBeGreaterThanOrEqual(1);
  });

  it('TC-004: approve action marks dialog as approved', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-approve-dialog-001'));
    });

    // After approving dialog-001, its card should show the approved status
    const card = screen.getByTestId('dialog-card-dialog-001');
    expect(card.textContent).toContain('✓ 通过');
  });

  it('TC-005: flag action marks dialog as flagged', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-flag-dialog-001'));
    });

    expect(screen.getByText('⚠ 标记')).toBeInTheDocument();
  });

  it('TC-006: progress reflects review completion', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    for (let i = 1; i <= 6; i++) {
      await act(async () => {
        fireEvent.click(screen.getByTestId(`btn-approve-dialog-${String(i).padStart(3, '0')}`));
      });
    }

    expect(screen.getByTestId('rehearsal-progress')).toHaveTextContent('已审 6 / 12 条');
  });

  it('TC-007: trap turn shows trap tag', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    const trapTags = screen.getAllByTestId(/^trap-tag-/);
    expect(trapTags.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('陷阱题').length).toBeGreaterThanOrEqual(1);
  });

  // T1F.7 · approve/flag buttons must POST /api/rehearsal/review
  it('TC-T1F7-A: approve triggers POST /api/rehearsal/review', async () => {
    // Seed state directly — bypass the fake-timer generate path so the test
    // focuses on the review API call wiring.
    useAdminStore.setState({
      rehearsalDialogs: [
        {
          id: 'dialog-001',
          scenario: {
            id: 'greeting',
            name_zh: '通用问候',
            intent: 'general_question',
            trap_question: '',
            degraded: false,
            keywords: [],
          },
          persona: {
            id: 'angry-refund',
            name_zh: '愤怒退款客户',
            traits: [],
            communication_style: 'aggressive',
          },
          turns: [],
          language: 'zh',
          review_status: 'pending',
        },
      ],
      rehearsalLoading: false,
    });

    postJSONMock.mockImplementation((_path: string, body?: unknown) =>
      Promise.resolve({
        status: 'ok',
        dialog_id: (body as { dialog_id: string }).dialog_id,
        review_status: 'approved',
      }),
    );

    render(<VirtualRehearsalStep tenantId="tenant-x" />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-approve-dialog-001'));
    });

    await waitFor(() => {
      const reviewCalls = postJSONMock.mock.calls.filter(
        ([path]) => path === '/api/rehearsal/review',
      );
      expect(reviewCalls.length).toBe(1);
      expect(reviewCalls[0][1]).toEqual({
        tenant_id: 'tenant-x',
        dialog_id: 'dialog-001',
        review_status: 'approved',
      });
    });
  });

  it('TC-T1F7-B: flag triggers POST /api/rehearsal/review with flagged status', async () => {
    useAdminStore.setState({
      rehearsalDialogs: [
        {
          id: 'dialog-002',
          scenario: {
            id: 'inquiry',
            name_zh: '基本咨询',
            intent: 'product_inquiry',
            trap_question: '',
            degraded: false,
            keywords: [],
          },
          persona: {
            id: 'price-sensitive',
            name_zh: '价格敏感客户',
            traits: [],
            communication_style: 'cautious',
          },
          turns: [],
          language: 'zh',
          review_status: 'pending',
        },
      ],
      rehearsalLoading: false,
    });

    postJSONMock.mockImplementation((_path: string, body?: unknown) =>
      Promise.resolve({
        status: 'ok',
        dialog_id: (body as { dialog_id: string }).dialog_id,
        review_status: (body as { review_status: string }).review_status,
      }),
    );

    render(<VirtualRehearsalStep tenantId="tenant-y" />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-flag-dialog-002'));
    });

    await waitFor(() => {
      const reviewCalls = postJSONMock.mock.calls.filter(
        ([path]) => path === '/api/rehearsal/review',
      );
      expect(reviewCalls.length).toBe(1);
      expect(reviewCalls[0][1]).toEqual({
        tenant_id: 'tenant-y',
        dialog_id: 'dialog-002',
        review_status: 'flagged',
      });
    });
  });

  it('TC-008: degraded scenario shows degraded tag', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    const degradedTags = screen.getAllByTestId(/^degraded-tag-/);
    expect(degradedTags.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('降级').length).toBeGreaterThanOrEqual(1);
  });
});
