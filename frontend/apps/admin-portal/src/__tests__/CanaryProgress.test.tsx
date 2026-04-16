import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CanaryProgress } from '../components/CanaryProgress';
import { useAdminStore } from '../store/adminStore';
import type { CanaryStateUI } from '../store/adminStore';

const MOCK_CANARY: CanaryStateUI = {
  stage: 'stage_25',
  percentage: 25,
  autoRollback: true,
  rolledBack: false,
  metrics: [
    { name: 'csat', baseline: 4.5, current: 4.3, breached: false },
    { name: 'resolution_rate', baseline: 0.85, current: 0.82, breached: false },
    { name: 'digest_rate', baseline: 0.90, current: 0.88, breached: false },
    { name: 'accept_wait_ms', baseline: 200, current: 350, breached: true },
    { name: 'complaint_rate', baseline: 0.02, current: 0.03, breached: false },
  ],
};

describe('CanaryProgress', () => {
  beforeEach(() => {
    useAdminStore.setState({ canaryState: null });
  });

  it('TC-001: shows empty state when no canary', () => {
    render(<CanaryProgress />);
    expect(screen.getByTestId('canary-progress')).toBeInTheDocument();
    expect(screen.getByTestId('canary-empty')).toBeInTheDocument();
  });

  it('TC-002: renders canary steps and percentage', () => {
    useAdminStore.setState({ canaryState: MOCK_CANARY });
    render(<CanaryProgress />);
    expect(screen.getByTestId('canary-steps')).toBeInTheDocument();
    expect(screen.getByTestId('canary-percentage')).toBeInTheDocument();
  });

  it('TC-003: shows 5 metrics in table', () => {
    useAdminStore.setState({ canaryState: MOCK_CANARY });
    render(<CanaryProgress />);
    expect(screen.getByTestId('canary-metrics-table')).toBeInTheDocument();
    expect(screen.getByText('CSAT 评分')).toBeInTheDocument();
    expect(screen.getByText('升级→结案率')).toBeInTheDocument();
    expect(screen.getByText('对话摘要率')).toBeInTheDocument();
    expect(screen.getByText('P95 响应时间(ms)')).toBeInTheDocument();
    expect(screen.getByText('投诉率')).toBeInTheDocument();
  });

  it('TC-004: breached metric shows red tag', () => {
    useAdminStore.setState({ canaryState: MOCK_CANARY });
    render(<CanaryProgress />);
    const breachedTags = screen.getAllByTestId('metric-breached');
    expect(breachedTags.length).toBe(1);
    expect(screen.getByTestId('breach-count')).toBeInTheDocument();
  });

  it('TC-005: healthy metrics show green tags', () => {
    useAdminStore.setState({ canaryState: MOCK_CANARY });
    render(<CanaryProgress />);
    const okTags = screen.getAllByTestId('metric-ok');
    expect(okTags.length).toBe(4);
  });

  it('TC-006: rolled back state shows red status', () => {
    useAdminStore.setState({
      canaryState: { ...MOCK_CANARY, rolledBack: true, percentage: 0 },
    });
    render(<CanaryProgress />);
    expect(screen.getByTestId('canary-status-tag').textContent).toBe('已回滚');
  });

  it('TC-007: stage steps reflect current stage', () => {
    useAdminStore.setState({ canaryState: MOCK_CANARY });
    render(<CanaryProgress />);
    // Steps shows: 未启动, 5%, 25%, 100%
    expect(screen.getByText('5%')).toBeInTheDocument();
    expect(screen.getAllByText('25%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText('未启动')).toBeInTheDocument();
  });
});
