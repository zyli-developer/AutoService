import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { initialState, useOperatorStore } from '../store/operatorStore';

// Antd requires matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

afterEach(() => {
  useOperatorStore.setState(initialState);
});
