import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';

const MOCK_SLA: Record<string, { p50: number; p95: number; count: number; min: number; max: number }> = {
  csat_score: { p50: 4.6, p95: 4.8, count: 100, min: 3.0, max: 5.0 },
  resolution_rate: { p50: 0.87, p95: 0.95, count: 100, min: 0.5, max: 1.0 },
  digest_rate: { p50: 0.91, p95: 0.98, count: 100, min: 0.6, max: 1.0 },
  first_reply_ms: { p50: 120, p95: 350, count: 100, min: 50, max: 500 },
  accept_ms: { p50: 200, p95: 600, count: 100, min: 80, max: 900 },
  complaint_rate: { p50: 0.02, p95: 0.05, count: 100, min: 0.0, max: 0.1 },
  ttfb_ms: { p50: 80, p95: 200, count: 100, min: 30, max: 300 },
};

vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.resolve(MOCK_SLA)),
  postJSON: vi.fn(() => Promise.resolve({})),
  postForm: vi.fn(() => Promise.resolve({})),
}));

// Mock sub-components that also make API calls
vi.mock('../components/CanaryProgress', () => ({ CanaryProgress: () => <div data-testid="canary-mock" /> }));
vi.mock('../components/TakeoverTrendChart', () => ({ TakeoverTrendChart: () => <div data-testid="trend-mock" /> }));
vi.mock('../components/LeaderboardTable', () => ({ LeaderboardTable: () => <div data-testid="leaderboard-mock" /> }));

import { DashboardTab } from '../components/DashboardTab';

describe('DashboardTab', () => {
  it('TC-01: renders 4 agent cards', async () => {
    await act(async () => {
      render(<DashboardTab />);
    });
    expect(screen.getByTestId('agent-card-customer')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-translate')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-lead')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-triage')).toBeInTheDocument();
  });

  it('TC-02: all agents show online status', async () => {
    await act(async () => {
      render(<DashboardTab />);
    });
    const cards = [
      screen.getByTestId('agent-card-customer'),
      screen.getByTestId('agent-card-translate'),
      screen.getByTestId('agent-card-lead'),
      screen.getByTestId('agent-card-triage'),
    ];
    cards.forEach((card) => {
      expect(card).toHaveTextContent('online');
    });
  });

  it('TC-03: renders metric cards with SLA data', async () => {
    await act(async () => {
      render(<DashboardTab />);
    });
    const csat = screen.getByTestId('metric-csat_score');
    expect(csat).toHaveTextContent('CSAT');
    expect(csat).toHaveTextContent('4.6');

    const resolution = screen.getByTestId('metric-resolution_rate');
    expect(resolution).toHaveTextContent('结案率');
    expect(resolution).toHaveTextContent('87.0%');

    const digest = screen.getByTestId('metric-digest_rate');
    expect(digest).toHaveTextContent('消化率');
    expect(digest).toHaveTextContent('91.0%');
  });
});
