import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ProposalsTab } from '../components/ProposalsTab';

const MOCK_PROPOSALS = [
  { id: 'prop_001', created_at: '2026-04-01', category: 'response_quality', title: '改进建议 #1', priority: 'high', status: 'draft', suggestion: '建议优化回复模板' },
  { id: 'prop_002', created_at: '2026-04-02', category: 'workflow', title: '改进建议 #2', priority: 'medium', status: 'draft', suggestion: '优化工作流' },
  { id: 'prop_003', created_at: '2026-04-03', category: 'knowledge_gap', title: '改进建议 #3', priority: 'low', status: 'draft', suggestion: '补充知识库' },
  { id: 'prop_004', created_at: '2026-04-04', category: 'tone', title: '改进建议 #4', priority: 'medium', status: 'accepted', suggestion: '调整语气' },
  { id: 'prop_005', created_at: '2026-04-05', category: 'response_quality', title: '改进建议 #5', priority: 'high', status: 'draft', suggestion: '改进响应' },
  { id: 'prop_006', created_at: '2026-04-06', category: 'workflow', title: '改进建议 #6', priority: 'low', status: 'rejected', suggestion: '简化流程' },
];

vi.mock('../api', () => ({
  fetchJSON: vi.fn(() => Promise.resolve(MOCK_PROPOSALS)),
  postJSON: vi.fn(() => Promise.resolve([])),
  postForm: vi.fn(() => Promise.resolve({})),
}));

describe('ProposalsTab', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('TC-001: renders title, filters, and proposal list area', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-filters')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-list')).toBeInTheDocument();
  });

  it('TC-002: loads 6 proposals', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    const cards = screen.getAllByTestId(/^proposal-card-/);
    expect(cards.length).toBe(6);
  });

  it('TC-003: filter buttons include all status options', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    const filters = screen.getByTestId('proposal-filters');
    expect(filters).toBeInTheDocument();
    const filterButtons = filters.querySelectorAll('button');
    const filterTexts = Array.from(filterButtons).map((b) => b.textContent);
    expect(filterTexts).toContain('全部');
    expect(filterTexts).toContain('待审核');
    expect(filterTexts).toContain('已接受');
    expect(filterTexts).toContain('已拒绝');
    expect(filterTexts).toContain('已阻止');
  });

  it('TC-005: proposal cards show status labels', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    // prop_004 is accepted -> 已接受
    expect(screen.getAllByText('已接受').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-006: proposals show priority in card', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    // Priority values rendered in cards
    expect(screen.getAllByText('high').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('medium').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('low').length).toBeGreaterThanOrEqual(1);
  });

  it('TC-007: stat-draft shows total count', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    expect(screen.getByTestId('stat-draft')).toHaveTextContent('6');
  });

  it('TC-008: proposal card shows title and suggestion', async () => {
    await act(async () => {
      render(<ProposalsTab />);
    });

    expect(screen.getByText('改进建议 #1')).toBeInTheDocument();
    expect(screen.getAllByText(/建议优化/).length).toBeGreaterThanOrEqual(1);
  });
});
