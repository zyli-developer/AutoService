import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useAdminStore } from '../store/adminStore';

vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.resolve({})),
  postJSON: vi.fn(() => Promise.resolve({})),
  postForm: vi.fn(() => Promise.resolve({
    tenant_id: 'test-tenant',
    souls: {
      customer: { kb_hit_count: 5, mode: 'dry_run', warnings: [] },
      translate: { kb_hit_count: 3, mode: 'dry_run', warnings: [] },
      lead: { kb_hit_count: 2, mode: 'dry_run', warnings: [] },
      triage: { kb_hit_count: 1, mode: 'dry_run', warnings: [] },
    },
    files_parsed: 0,
  })),
}));

import { MaterialUploadStep, INDUSTRY_OPTIONS } from '../components/wizard/MaterialUploadStep';

describe('MaterialUploadStep', () => {
  beforeEach(() => {
    useAdminStore.setState({
      wizardFormData: { brandName: '', industry: 'general', languages: ['zh', 'en'], websiteUrl: '', extraContext: '', files: [] },
      generating: false,
      generationResult: null,
    });
  });

  it('TC-001: renders form with all fields', () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);
    expect(screen.getByTestId('material-upload-step')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('MyAwesomeStore')).toBeInTheDocument();
    expect(screen.getByTestId('select-industry')).toBeInTheDocument();
    expect(screen.getByTestId('file-upload')).toBeInTheDocument();
    expect(screen.getByTestId('btn-generate')).toBeInTheDocument();
  });

  it('TC-002: generate button is not disabled when brandName is empty (component does not enforce)', () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);
    const btn = screen.getByTestId('btn-generate');
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it('TC-003: file upload accept attribute is .pdf,.csv,.txt', () => {
    const { container } = render(<MaterialUploadStep tenantId="test-tenant" />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).not.toBeNull();
    expect(fileInput.accept).toBe('.pdf,.csv,.txt');
  });

  it('TC-004: submit triggers generation + shows result', async () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);

    const brandInput = screen.getByPlaceholderText('MyAwesomeStore');
    await act(async () => {
      fireEvent.change(brandInput, { target: { value: 'TestBrand' } });
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate'));
    });

    expect(screen.getByTestId('generation-result')).toBeInTheDocument();
  });

  it('TC-005: generation result shows 4 agent statuses', async () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);

    const brandInput = screen.getByPlaceholderText('MyAwesomeStore');
    await act(async () => {
      fireEvent.change(brandInput, { target: { value: 'TestBrand' } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate'));
    });

    expect(screen.getByTestId('generation-result')).toBeInTheDocument();
    expect(screen.getByTestId('agent-status-customer')).toBeInTheDocument();
    expect(screen.getByTestId('agent-status-translate')).toBeInTheDocument();
    expect(screen.getByTestId('agent-status-lead')).toBeInTheDocument();
    expect(screen.getByTestId('agent-status-triage')).toBeInTheDocument();
  });

  it('TC-006: generation result shows agent role names', async () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);

    const brandInput = screen.getByPlaceholderText('MyAwesomeStore');
    await act(async () => {
      fireEvent.change(brandInput, { target: { value: 'TestBrand' } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate'));
    });

    expect(screen.getByText('customer Agent')).toBeInTheDocument();
    expect(screen.getByText('translate Agent')).toBeInTheDocument();
    expect(screen.getByText('lead Agent')).toBeInTheDocument();
    expect(screen.getByText('triage Agent')).toBeInTheDocument();
  });

  it('TC-007: industry options match backend enum', () => {
    const expectedValues = ['ecommerce', 'saas', 'finance', 'healthcare', 'education', 'general'];
    const actualValues = INDUSTRY_OPTIONS.map((opt) => opt.value);
    expectedValues.forEach((val) => {
      expect(actualValues).toContain(val);
    });
    expect(actualValues).toHaveLength(6);
  });
});
