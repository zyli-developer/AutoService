import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DashboardTab } from '../components/DashboardTab';

describe('DashboardTab', () => {
  it('TC-01: renders 4 agent cards', () => {
    render(<DashboardTab />);
    expect(screen.getByTestId('agent-card-customer')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-translate')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-lead')).toBeInTheDocument();
    expect(screen.getByTestId('agent-card-triage')).toBeInTheDocument();
  });

  it('TC-02: all agents show online status', () => {
    render(<DashboardTab />);
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

  it('TC-03: renders 3 metric cards with values', () => {
    render(<DashboardTab />);
    const takeover = screen.getByTestId('metric-takeover');
    expect(takeover).toHaveTextContent('接管次数');
    expect(takeover).toHaveTextContent('23');

    const csat = screen.getByTestId('metric-csat');
    expect(csat).toHaveTextContent('CSAT');
    expect(csat).toHaveTextContent('4.6');

    const resolution = screen.getByTestId('metric-resolution');
    expect(resolution).toHaveTextContent('升级→结案率');
    expect(resolution).toHaveTextContent('87');
  });
});
