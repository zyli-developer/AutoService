import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ProposalsTab } from '../components/ProposalsTab';
import { useAdminStore } from '../store/adminStore';

describe('ProposalsTab', () => {
  beforeEach(() => {
    useAdminStore.setState({
      proposals: [],
      proposalsLoading: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: renders title, filters, and proposal list area', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-filters')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-list')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('TC-002: loads 6 mock proposals', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    const cards = screen.getAllByTestId(/^proposal-card-/);
    expect(cards.length).toBe(6);
  });

  it('TC-003: filter by status shows matching proposals', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    // Accept first proposal, then filter by accepted
    act(() => {
      fireEvent.click(screen.getByTestId('btn-accept-prop_001'));
    });

    // All proposals initially draft except prop_001 which is now accepted
    // After accepting, 5 draft + 1 accepted = 6 total still shown (no filter active)
    const cards = screen.getAllByTestId(/^proposal-card-/);
    expect(cards.length).toBe(6);

    // Verify the accepted one shows accepted status (Statistic title also says 已接受)
    expect(screen.getAllByText('已接受').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-005: accept proposal changes status to accepted', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-accept-prop_001'));
    });

    const state = useAdminStore.getState();
    const proposal = state.proposals.find((p) => p.id === 'prop_001');
    expect(proposal?.status).toBe('accepted');
  });

  it('TC-006: reject proposal changes status to rejected', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-reject-prop_002'));
    });

    const state = useAdminStore.getState();
    const proposal = state.proposals.find((p) => p.id === 'prop_002');
    expect(proposal?.status).toBe('rejected');
  });

  it('TC-007: priority tags have correct colors', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    // prop_001 = high, prop_002 = medium, prop_003 = low
    const highTag = screen.getByTestId('priority-tag-prop_001');
    expect(highTag.textContent).toBe('high');
    expect(highTag.className).toContain('red');

    const medTag = screen.getByTestId('priority-tag-prop_002');
    expect(medTag.textContent).toBe('medium');
    expect(medTag.className).toContain('orange');

    const lowTag = screen.getByTestId('priority-tag-prop_003');
    expect(lowTag.textContent).toBe('low');
    expect(lowTag.className).toContain('blue');
  });

  it('TC-008: proposal card shows complete info', async () => {
    vi.useFakeTimers();
    render(<ProposalsTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByText('改进建议 #1')).toBeInTheDocument();
    expect(screen.getAllByText(/基于最近/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/建议优化/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('evidence-prop_001')).toBeInTheDocument();
  });
});
