import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { BillingTab } from '../components/BillingTab';

describe('BillingTab', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: renders billing page with title', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
    expect(screen.getByText('账单管理')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('TC-002: loads 3 mock invoices', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    expect(screen.getByTestId('billing-loading')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('invoice-detail')).toBeInTheDocument();
    expect(screen.getByTestId('invoice-history')).toBeInTheDocument();
  });

  it('TC-003: shows invoice detail with total, conversations, period', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('stat-total')).toBeInTheDocument();
    expect(screen.getByTestId('stat-conversations')).toBeInTheDocument();
    expect(screen.getByTestId('stat-period')).toBeInTheDocument();
  });

  it('TC-004: breakdown table shows tier rows', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('breakdown-table')).toBeInTheDocument();
    expect(screen.getByText('free')).toBeInTheDocument();
    expect(screen.getByText('starter')).toBeInTheDocument();
  });

  it('TC-005: export CSV button exists', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('btn-export-csv')).toBeInTheDocument();
  });

  it('TC-006: history table shows all invoices', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('history-table')).toBeInTheDocument();
    // 2026-04 appears in select, stat, and history table
    expect(screen.getAllByText('2026-04').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('2026-03').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('2026-02').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-007: period selector shows options', async () => {
    vi.useFakeTimers();
    render(<BillingTab />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByTestId('select-period')).toBeInTheDocument();
    expect(screen.getByTestId('billing-controls')).toBeInTheDocument();
  });
});
