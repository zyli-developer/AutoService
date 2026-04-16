import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { useChatStore, initialState } from '../store/chatStore';
import { initGlobalI18n } from '@autoservice/i18n';

// Initialize the global i18next singleton for all tests (en locale).
// Components using useTranslation() without a provider will use this.
initGlobalI18n('en');

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useChatStore.setState(initialState);
  sessionStorage.clear();  // clear cursor storage between tests
});
