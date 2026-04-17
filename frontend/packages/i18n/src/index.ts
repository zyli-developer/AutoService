import i18next, { type i18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zhCN from './locales/zh-CN.json';

const resources = {
  en: { translation: en },
  'zh-CN': { translation: zhCN },
};

/**
 * T1B.6: Create an isolated i18n instance (for I18nextProvider / SSR / test isolation).
 * Will be extended for 22 locales + namespace lazy-loading.
 */
export function createI18n(defaultLng: string = 'zh-CN'): i18n {
  const instance = i18next.createInstance();
  instance.use(initReactI18next).init({
    lng: defaultLng,
    fallbackLng: 'en',
    resources,
    interpolation: { escapeValue: false },
  });
  return instance;
}

/**
 * Initialize the global i18next singleton (used by useTranslation() without a provider).
 * Call this in test setup or server entry points where I18nextProvider is not available.
 */
export function initGlobalI18n(defaultLng: string = 'en'): void {
  if (i18next.isInitialized) return;
  i18next.use(initReactI18next).init({
    lng: defaultLng,
    fallbackLng: 'en',
    resources,
    interpolation: { escapeValue: false },
  });
}

export { useTranslation, Trans, I18nextProvider } from 'react-i18next';
