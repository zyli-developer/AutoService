import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { BillingTab } from '../components/BillingTab';

const MOCK_INVOICES = [
  {
    period: '2026-04',
    total: 128.50,
    breakdown: [
      { tier: 'free', count: 10, rate: 0, subtotal: 0 },
      { tier: 'starter', count: 50, rate: 1.5, subtotal: 75.0 },
      { tier: 'pro', count: 20, rate: 2.675, subtotal: 53.50 },
    ],
    status: 'generated',
  },
  {
    period: '2026-03',
    total: 95.00,
    breakdown: [{ tier: 'starter', count: 40, rate: 1.5, subtotal: 60.0 }],
    status: 'paid',
  },
  {
    period: '2026-02',
    total: 60.00,
    breakdown: [{ tier: 'free', count: 20, rate: 0, subtotal: 0 }],
    status: 'paid',
  },
];

vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.resolve(MOCK_INVOICES)),
  postJSON: vi.fn(() => Promise.resolve({})),
  postForm: vi.fn(() => Promise.resolve({})),
}));

describe('BillingTab', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('TC-001: renders billing tab container', async () => {
    await act(async () => {
      render(<BillingTab />);
    });
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
  });

  it('TC-002: loads invoices and shows invoice detail', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByTestId('invoice-detail')).toBeInTheDocument();
    expect(screen.getByTestId('billing-controls')).toBeInTheDocument();
  });

  it('TC-003: shows invoice detail with total', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByTestId('stat-total')).toBeInTheDocument();
    expect(screen.getByTestId('stat-total')).toHaveTextContent('$128.50');
  });

  it('TC-004: breakdown card shows tier rows', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByTestId('breakdown-card')).toBeInTheDocument();
    expect(screen.getByText(/free/)).toBeInTheDocument();
    expect(screen.getByText(/starter/)).toBeInTheDocument();
  });

  it('TC-005: shows status in invoice detail', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByText('generated')).toBeInTheDocument();
  });

  it('TC-006: billing controls show all periods', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByText('2026-04')).toBeInTheDocument();
    expect(screen.getByText('2026-03')).toBeInTheDocument();
    expect(screen.getByText('2026-02')).toBeInTheDocument();
  });

  it('TC-007: billing controls allow period selection', async () => {
    await act(async () => {
      render(<BillingTab />);
    });

    expect(screen.getByTestId('billing-controls')).toBeInTheDocument();
    // 3 period buttons rendered
    const buttons = screen.getByTestId('billing-controls').querySelectorAll('button');
    expect(buttons.length).toBe(3);
  });
});
