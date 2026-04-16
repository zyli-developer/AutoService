import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MaterialUploadStep, INDUSTRY_OPTIONS } from '../components/wizard/MaterialUploadStep';
import { useAdminStore } from '../store/adminStore';

describe('MaterialUploadStep', () => {
  beforeEach(() => {
    // Reset wizard state between tests for isolation
    useAdminStore.setState({
      wizardFormData: { brandName: '', industry: 'general', languages: ['zh', 'en'], websiteUrl: '', extraContext: '', files: [] },
      generating: false,
      generationResult: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: renders form with all fields', () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);
    expect(screen.getByTestId('material-upload-step')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('请输入品牌名称')).toBeInTheDocument();
    expect(screen.getByTestId('select-industry')).toBeInTheDocument();
    expect(screen.getByTestId('upload-area')).toBeInTheDocument();
    expect(screen.getByTestId('btn-generate')).toBeInTheDocument();
  });

  it('TC-002: brand name required validation — generate button disabled when brandName is empty', () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);
    const btn = screen.getByTestId('btn-generate');
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it('TC-003: file upload accept attribute is .pdf,.csv,.txt', () => {
    const { container } = render(<MaterialUploadStep tenantId="test-tenant" />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).not.toBeNull();
    expect(fileInput.accept).toBe('.pdf,.csv,.txt');
  });

  it('TC-004: submit triggers generation + loading state', async () => {
    vi.useFakeTimers();
    render(<MaterialUploadStep tenantId="test-tenant" />);

    const brandInput = screen.getByPlaceholderText('请输入品牌名称');
    act(() => {
      fireEvent.change(brandInput, { target: { value: 'TestBrand' } });
    });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-generate'));
    });

    expect(screen.getByTestId('generating-indicator')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByTestId('generation-result')).toBeInTheDocument();
  });

  it('TC-005: generation result shows 4 role cards', async () => {
    vi.useFakeTimers();
    render(<MaterialUploadStep tenantId="test-tenant" />);

    const brandInput = screen.getByPlaceholderText('请输入品牌名称');
    act(() => {
      fireEvent.change(brandInput, { target: { value: 'TestBrand' } });
    });
    act(() => {
      fireEvent.click(screen.getByTestId('btn-generate'));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    const result = screen.getByTestId('generation-result');
    expect(result).toBeInTheDocument();
    expect(screen.getByText('customer')).toBeInTheDocument();
    expect(screen.getByText('translate')).toBeInTheDocument();
    expect(screen.getByText('lead')).toBeInTheDocument();
    expect(screen.getByText('triage')).toBeInTheDocument();
  });

  it('TC-006: next button disabled before generation', () => {
    render(<MaterialUploadStep tenantId="test-tenant" />);
    const nextBtn = screen.getByTestId('btn-next-step');
    expect((nextBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it('TC-007: industry options match backend enum', () => {
    const expectedValues = ['ecommerce', 'saas', 'finance', 'healthcare', 'education', 'telecom', 'general'];
    const actualValues = INDUSTRY_OPTIONS.map((opt) => opt.value);
    expectedValues.forEach((val) => {
      expect(actualValues).toContain(val);
    });
    expect(actualValues).toHaveLength(7);
  });
});
