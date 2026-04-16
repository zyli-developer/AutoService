import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { useChatStore, initialState } from '../store/chatStore';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useChatStore.setState(initialState);
});
