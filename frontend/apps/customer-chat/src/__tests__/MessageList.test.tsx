import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MerchantSite } from '../components/MerchantSite';

describe('MerchantSite', () => {
  it('renders hero section', () => {
    render(<MerchantSite />);
    expect(screen.getByText('\u6B22\u8FCE\u5149\u4E34')).toBeInTheDocument();
  });

  it('renders product cards', () => {
    render(<MerchantSite />);
    expect(screen.getByText('\u5957\u9910 A')).toBeInTheDocument();
    expect(screen.getByText('\u5957\u9910 B')).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<MerchantSite />);
    expect(screen.getByText('\u9996\u9875')).toBeInTheDocument();
    expect(screen.getByText('\u4EA7\u54C1')).toBeInTheDocument();
    expect(screen.getByText('\u5173\u4E8E')).toBeInTheDocument();
  });

  it('renders merchant logo', () => {
    render(<MerchantSite />);
    expect(screen.getByTestId('merchant-logo')).toBeInTheDocument();
  });
});
