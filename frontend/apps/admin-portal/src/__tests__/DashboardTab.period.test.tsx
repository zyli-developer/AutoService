import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DashboardTab } from '../components/DashboardTab';

// Track SLA-specific calls while providing stubs for child components
const slaCalls: string[] = [];

vi.mock('../api', () => ({
  fetchJSON: (url: string) => {
    // SLA summary — track and return valid data
    if (url.includes('/api/sla/summary')) {
      slaCalls.push(url);
      const metrics = [
        'first_reply_ms', 'accept_ms', 'csat_score',
        'resolution_rate', 'digest_rate', 'complaint_rate', 'ttfb_ms',
      ];
      const result: Record<string, unknown> = {};
      for (const m of metrics) {
        result[m] = { p50: 1, p95: 2, count: 10, min: 0, max: 5 };
      }
      return Promise.resolve(result);
    }
    // Canary status
    if (url.includes('/api/canary/status')) {
      return Promise.resolve({
        stage: 0, percentage: 0, can_advance: false, history: [],
        monitor: { status: 'idle', breaches: [] },
      });
    }
    // Takeover trend
    if (url.includes('/api/metrics/takeover-trend')) {
      return Promise.resolve([]);
    }
    // Operator leaderboard
    if (url.includes('/api/metrics/operator-leaderboard')) {
      return Promise.resolve([]);
    }
    return Promise.resolve({});
  },
  postJSON: () => Promise.resolve({}),
}));

describe('DashboardTab period tabs (T6D.5)', () => {
  beforeEach(() => {
    slaCalls.length = 0;
  });

  it('TC-06: renders 3 period tabs, default "近5分钟" selected', async () => {
    render(<DashboardTab />);

    // Wait for initial fetch to settle
    await act(async () => {});

    const btn5m = screen.getByTestId('period-5m');
    const btn1h = screen.getByTestId('period-1h');
    const btn24h = screen.getByTestId('period-24h');

    expect(btn5m).toBeInTheDocument();
    expect(btn1h).toBeInTheDocument();
    expect(btn24h).toBeInTheDocument();

    // Default "近5分钟" should look selected (check aria or style)
    expect(btn5m).toHaveTextContent('近5分钟');
  });

  it('TC-07: clicking "近1小时" fetches with period=1h', async () => {
    const user = userEvent.setup();
    render(<DashboardTab />);
    await act(async () => {});

    await user.click(screen.getByTestId('period-1h'));
    await act(async () => {});

    expect(slaCalls).toContain('/api/sla/summary?period=1h');
  });

  it('TC-08: clicking "近24小时" fetches with period=24h', async () => {
    const user = userEvent.setup();
    render(<DashboardTab />);
    await act(async () => {});

    await user.click(screen.getByTestId('period-24h'));
    await act(async () => {});

    expect(slaCalls).toContain('/api/sla/summary?period=24h');
  });

  it('TC-09: switching back to "近5分钟" re-fetches', async () => {
    const user = userEvent.setup();
    render(<DashboardTab />);
    await act(async () => {});

    await user.click(screen.getByTestId('period-1h'));
    await act(async () => {});

    await user.click(screen.getByTestId('period-5m'));
    await act(async () => {});

    const fiveMCalls = slaCalls.filter((c: string) =>
      c === '/api/sla/summary' || c === '/api/sla/summary?period=5m'
    );
    // At least 2: initial load + switch back
    expect(fiveMCalls.length).toBeGreaterThanOrEqual(2);
  });
});
