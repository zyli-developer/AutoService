import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { VirtualRehearsalStep } from '../components/wizard/VirtualRehearsalStep';
import { useAdminStore } from '../store/adminStore';

describe('VirtualRehearsalStep', () => {
  beforeEach(() => {
    useAdminStore.setState({
      rehearsalDialogs: [],
      rehearsalLoading: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: renders page with title, start button, and next button', () => {
    render(<VirtualRehearsalStep tenantId="test-tenant" />);
    expect(screen.getByTestId('virtual-rehearsal-step')).toBeInTheDocument();
    expect(screen.getByTestId('btn-start-rehearsal')).toBeInTheDocument();
    expect(screen.getByTestId('btn-next-step')).toBeInTheDocument();
  });

  it('TC-002: start rehearsal shows loading then dialog cards', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
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

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getAllByText('通用问候').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('愤怒退款客户').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('激进').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-004: approve action marks dialog as approved', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-approve-dialog-001'));
    });

    expect(screen.getByTestId('dialog-card-dialog-001').querySelector('[class*="green"]') || screen.getByText('已通过')).toBeInTheDocument();
  });

  it('TC-005: flag action marks dialog as flagged', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-flag-dialog-001'));
    });

    expect(screen.getByText('已标记')).toBeInTheDocument();
  });

  it('TC-006: progress bar reflects review completion', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    for (let i = 1; i <= 6; i++) {
      act(() => {
        fireEvent.click(screen.getByTestId(`btn-approve-dialog-${String(i).padStart(3, '0')}`));
      });
    }

    expect(screen.getByText('6/12 已审阅')).toBeInTheDocument();
  });

  it('TC-007: next button disabled before all reviewed', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-approve-dialog-001'));
    });

    const btn = screen.getByTestId('btn-next-step') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('TC-008: next button enabled after all reviewed', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    for (let i = 1; i <= 12; i++) {
      act(() => {
        fireEvent.click(screen.getByTestId(`btn-approve-dialog-${String(i).padStart(3, '0')}`));
      });
    }

    const btn = screen.getByTestId('btn-next-step') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('TC-009: trap turn shows trap tag', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    const trapTags = screen.getAllByTestId(/^trap-tag-/);
    expect(trapTags.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('陷阱题').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-010: degraded scenario shows degraded tag', async () => {
    vi.useFakeTimers();
    render(<VirtualRehearsalStep tenantId="test-tenant" />);

    act(() => {
      fireEvent.click(screen.getByTestId('btn-start-rehearsal'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    const degradedTags = screen.getAllByTestId(/^degraded-tag-/);
    expect(degradedTags.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('降级场景').length).toBeGreaterThanOrEqual(1);
  });
});
