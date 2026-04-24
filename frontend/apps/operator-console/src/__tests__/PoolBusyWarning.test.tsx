import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useOperatorStore, INITIAL_POOL_STATUS } from '../store/operatorStore';
import { PoolBusyWarning } from '../components/PoolBusyWarning';

/**
 * Replaces ConcurrencyWarning.test.tsx. The warning is now driven by the
 * real cc_pool snapshot (`poolStatus`) rather than a fake per-operator cap.
 */
describe('PoolBusyWarning', () => {
  beforeEach(() => {
    useOperatorStore.setState({ poolStatus: INITIAL_POOL_STATUS });
  });

  it('hides when pool not started (fresh boot / POOL_MODE=0)', () => {
    useOperatorStore.setState({
      poolStatus: { ...INITIAL_POOL_STATUS, started: false, maxSize: 5, checkedOut: 5 },
    });
    const { container } = render(<PoolBusyWarning />);
    expect(container.innerHTML).toBe('');
  });

  it('hides when maxSize is 0 (degraded snapshot)', () => {
    useOperatorStore.setState({
      poolStatus: { ...INITIAL_POOL_STATUS, started: true, maxSize: 0, checkedOut: 0 },
    });
    const { container } = render(<PoolBusyWarning />);
    expect(container.innerHTML).toBe('');
  });

  it('hides when pool has headroom (checkedOut < max-1)', () => {
    useOperatorStore.setState({
      poolStatus: { ...INITIAL_POOL_STATUS, started: true, maxSize: 5, checkedOut: 2 },
    });
    const { container } = render(<PoolBusyWarning />);
    expect(container.innerHTML).toBe('');
  });

  it('shows "approaching" warn state at max-1', () => {
    useOperatorStore.setState({
      poolStatus: { ...INITIAL_POOL_STATUS, started: true, maxSize: 5, checkedOut: 4 },
    });
    render(<PoolBusyWarning />);
    const el = screen.getByTestId('concurrency-warning');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('warn');
    expect(el.className).not.toContain('danger');
    expect(el).toHaveTextContent('4');
    expect(el).toHaveTextContent('5');
  });

  it('shows "at capacity" danger state when checkedOut >= max', () => {
    useOperatorStore.setState({
      poolStatus: { ...INITIAL_POOL_STATUS, started: true, maxSize: 5, checkedOut: 5 },
    });
    render(<PoolBusyWarning />);
    const el = screen.getByTestId('concurrency-warning');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('danger');
  });
});
