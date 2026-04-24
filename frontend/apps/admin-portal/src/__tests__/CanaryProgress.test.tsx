import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

const mockFetchJSON = vi.fn();

vi.mock('../api', () => ({
  fetchJSON: (...args: unknown[]) => mockFetchJSON(...args),
  postJSON: vi.fn(() => Promise.resolve({})),
  postForm: vi.fn(() => Promise.resolve({})),
}));

import { CanaryProgress } from '../components/CanaryProgress';

const MOCK_CANARY_WITH_BREACHES = {
  stage: 2,
  percentage: 25,
  can_advance: true,
  history: [],
  monitor: {
    status: 'watching',
    breaches: [
      { metric: 'accept_wait_ms', baseline: 200, current: 350 },
    ],
  },
};

const MOCK_CANARY_CLEAN = {
  stage: 2,
  percentage: 25,
  can_advance: true,
  history: [],
  monitor: {
    status: 'healthy',
  },
};

const MOCK_CANARY_ROLLED_BACK = {
  stage: 0,
  percentage: 0,
  can_advance: false,
  history: [],
  monitor: {
    status: '已回滚',
  },
};

describe('CanaryProgress', () => {
  beforeEach(() => {
    mockFetchJSON.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('TC-001: shows empty state when API returns no data', async () => {
    mockFetchJSON.mockRejectedValueOnce(new Error('fail'));
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByTestId('canary-progress')).toBeInTheDocument();
    expect(screen.getByTestId('canary-empty')).toBeInTheDocument();
  });

  it('TC-002: renders canary steps and percentage', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_CLEAN);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByTestId('canary-steps')).toBeInTheDocument();
    expect(screen.getByTestId('canary-percentage')).toBeInTheDocument();
  });

  it('TC-003: shows monitor status', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_CLEAN);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByTestId('canary-status-tag')).toHaveTextContent('25% · healthy');
  });

  it('TC-004: breached metrics show in metrics table', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_WITH_BREACHES);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByTestId('canary-metrics-table')).toBeInTheDocument();
    const breachedTags = screen.getAllByTestId('metric-breached');
    expect(breachedTags.length).toBe(1);
    expect(screen.getByTestId('breach-count')).toBeInTheDocument();
    expect(screen.getByTestId('breach-count')).toHaveTextContent('1 项指标超阈值');
  });

  it('TC-005: clean canary has no metrics table', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_CLEAN);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.queryByTestId('canary-metrics-table')).not.toBeInTheDocument();
  });

  it('TC-006: rolled back state shows status text', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_ROLLED_BACK);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByTestId('canary-status-tag').textContent).toBe('0% · 已回滚');
  });

  it('TC-007: stage steps show percentage labels', async () => {
    mockFetchJSON.mockResolvedValueOnce(MOCK_CANARY_WITH_BREACHES);
    await act(async () => {
      render(<CanaryProgress />);
    });
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.getByText('5%')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
  });
});
