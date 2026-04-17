import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MerchantSite } from '../components/MerchantSite';

describe('MerchantSite', () => {
  it('renders hero section', () => {
    render(<MerchantSite />);
    expect(screen.getByText('欢迎光临')).toBeInTheDocument();
  });

  it('renders product cards', () => {
    render(<MerchantSite />);
    expect(screen.getByText('套餐 A')).toBeInTheDocument();
    expect(screen.getByText('套餐 B')).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<MerchantSite />);
    expect(screen.getByText('首页')).toBeInTheDocument();
    expect(screen.getByText('产品')).toBeInTheDocument();
    expect(screen.getByText('关于')).toBeInTheDocument();
  });

  it('renders merchant logo', () => {
    render(<MerchantSite />);
    expect(screen.getByTestId('merchant-logo')).toBeInTheDocument();
  });
});
