import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ComplianceCheckStep } from '../components/wizard/ComplianceCheckStep';

describe('ComplianceCheckStep', () => {
  it('TC-01: renders 16 rows in table', () => {
    render(<ComplianceCheckStep />);
    const table = screen.getByTestId('compliance-table');
    // Each data row is inside tbody
    const rows = table.querySelectorAll('tbody tr');
    expect(rows.length).toBe(16);
  });

  it('TC-02: summary shows correct counts', () => {
    render(<ComplianceCheckStep />);
    const summary = screen.getByTestId('compliance-summary');
    expect(summary.textContent).toContain('通过 12/16');
    expect(summary.textContent).toContain('警告 2');
    expect(summary.textContent).toContain('失败 2');
  });

  it('TC-03: alert shown when failures exist', () => {
    render(<ComplianceCheckStep />);
    const alert = screen.getByTestId('compliance-alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('存在未通过项');
  });

  it('TC-04: pass rules show green tag, fail rules show red tag', () => {
    render(<ComplianceCheckStep />);
    const table = screen.getByTestId('compliance-table');
    const tags = table.querySelectorAll('.ant-tag');

    const greenTags = Array.from(tags).filter((tag) =>
      tag.classList.contains('ant-tag-green'),
    );
    const redTags = Array.from(tags).filter((tag) =>
      tag.classList.contains('ant-tag-red'),
    );

    expect(greenTags.length).toBe(12);
    expect(redTags.length).toBe(2);
  });
});
