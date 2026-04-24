import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';
import { initialState, useAdminStore } from '../store/adminStore';

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

// jsdom lacks scrollIntoView; ManagementChat calls it after every message.
Element.prototype.scrollIntoView = vi.fn();

afterEach(() => {
  useAdminStore.setState(initialState);
});
