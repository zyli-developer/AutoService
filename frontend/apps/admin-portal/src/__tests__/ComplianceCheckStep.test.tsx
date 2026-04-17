import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';

const MOCK_REPORT = {
  tenant_id: 'test-tenant',
  risk_level: 'medium',
  total_rules: 16,
  passed: 12,
  failed: 4,
  pass_rate: 0.75,
  results: [
    ...Array.from({ length: 12 }, (_, i) => ({
      rule_id: `R${String(i + 1).padStart(3, '0')}`,
      name: `Rule ${i + 1}`,
      severity: 'info',
      passed: true,
      field: `field_${i}`,
      remediation_doc: '',
    })),
    ...Array.from({ length: 4 }, (_, i) => ({
      rule_id: `R${String(i + 13).padStart(3, '0')}`,
      name: `Fail Rule ${i + 1}`,
      severity: 'critical',
      passed: false,
      field: `field_${i + 12}`,
      remediation_doc: '',
    })),
  ],
};

vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.resolve({})),
  postJSON: vi.fn(() => Promise.resolve(MOCK_REPORT)),
  postForm: vi.fn(() => Promise.resolve({})),
}));

import { ComplianceCheckStep } from '../components/wizard/ComplianceCheckStep';

describe('ComplianceCheckStep', () => {
  it('TC-01: renders 16 rules', async () => {
    await act(async () => {
      render(<ComplianceCheckStep />);
    });
    const table = screen.getByTestId('compliance-table');
    const rows = table.querySelectorAll('.cs-row');
    expect(rows.length).toBe(16);
  });

  it('TC-02: summary shows risk level and pass count', async () => {
    await act(async () => {
      render(<ComplianceCheckStep />);
    });
    const summary = screen.getByTestId('compliance-summary');
    expect(summary.textContent).toContain('medium');
  });

  it('TC-03: alert shown when failures exist', async () => {
    await act(async () => {
      render(<ComplianceCheckStep />);
    });
    const alert = screen.getByTestId('compliance-alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain('4 项未通过');
  });

  it('TC-04: pass rules show pass label, fail rules show fail label', async () => {
    await act(async () => {
      render(<ComplianceCheckStep />);
    });
    const table = screen.getByTestId('compliance-table');
    const allLabels = table.querySelectorAll('span');
    const passLabels = Array.from(allLabels).filter((el) => el.textContent === '通过');
    const failLabels = Array.from(allLabels).filter((el) => el.textContent === '失败');
    expect(passLabels.length).toBe(12);
    expect(failLabels.length).toBe(4);
  });
});
