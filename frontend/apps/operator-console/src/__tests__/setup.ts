import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { initGlobalI18n } from '@autoservice/i18n';
import { initialState, useOperatorStore } from '../store/operatorStore';

initGlobalI18n('zh-CN');

// matchMedia stub for jsdom environment
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
