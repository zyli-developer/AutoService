import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ComplianceCheckStep } from '../components/wizard/ComplianceCheckStep';

describe('ComplianceCheckStep', () => {
  it('TC-01: renders 16 rules', () => {
    render(<ComplianceCheckStep />);
    const table = screen.getByTestId('compliance-table');
    const rows = table.querySelectorAll('.cs-row');
    expect(rows.length).toBe(16);
  });

  it('TC-02: summary shows correct counts', () => {
    render(<ComplianceCheckStep />);
    const summary = screen.getByTestId('compliance-summary');
    expect(summary.textContent).toContain('\u901A\u8FC7 12/16');
    expect(summary.textContent).toContain('\u8B66\u544A 2');
    expect(summary.textContent).toContain('\u5931\u8D25 2');
  });

  it('TC-03: alert shown when failures exist', () => {
    render(<ComplianceCheckStep />);
    const alert = screen.getByTestId('compliance-alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('\u5B58\u5728\u672A\u901A\u8FC7\u9879');
  });

  it('TC-04: pass rules show pass label, fail rules show fail label', () => {
    render(<ComplianceCheckStep />);
    const table = screen.getByTestId('compliance-table');
    const allLabels = table.querySelectorAll('span');
    const passLabels = Array.from(allLabels).filter((el) => el.textContent === '\u901A\u8FC7');
    const failLabels = Array.from(allLabels).filter((el) => el.textContent === '\u5931\u8D25');
    expect(passLabels.length).toBe(12);
    expect(failLabels.length).toBe(2);
  });
});
