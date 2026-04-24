import i18next, { type i18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zhCN from './locales/zh-CN.json';

const resources = {
  en: { translation: en },
  'zh-CN': { translation: zhCN },
};

const STORAGE_KEY = 'autoservice.language';

/**
 * List of languages shipped in the bundle. Extend by:
 *   1. Add src/locales/<code>.json
 *   2. Import + register in `resources` above
 *   3. Append an entry here (label shown in LanguageSwitcher)
 */
export interface SupportedLanguage {
  code: string;
  nativeLabel: string;
  englishLabel: string;
}

export const SUPPORTED_LANGUAGES: SupportedLanguage[] = [
  { code: 'zh-CN', nativeLabel: '中文', englishLabel: 'Chinese' },
  { code: 'en', nativeLabel: 'EN', englishLabel: 'English' },
];

export function isSupportedLanguage(code: string): boolean {
  return SUPPORTED_LANGUAGES.some((l) => l.code === code);
}

/**
 * Detect the initial language:
 *   1. localStorage (user previously picked)
 *   2. navigator.language (browser preference; normalized)
 *   3. fallback to zh-CN
 */
export function detectInitialLanguage(fallback: string = 'zh-CN'): string {
  try {
    const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    if (stored && isSupportedLanguage(stored)) return stored;
  } catch {
    /* localStorage unavailable (SSR/tests): fall through */
  }
  try {
    const nav =
      typeof navigator !== 'undefined' && navigator.language ? navigator.language : '';
    if (nav) {
      if (isSupportedLanguage(nav)) return nav;
      // try prefix match: "en-US" → "en"
      const prefix = nav.split('-')[0];
      const match = SUPPORTED_LANGUAGES.find(
        (l) => l.code === prefix || l.code.split('-')[0] === prefix,
      );
      if (match) return match.code;
    }
  } catch {
    /* navigator unavailable */
  }
  return fallback;
}

/**
 * Persist the user's language choice across reloads and notify all i18next
 * instances created from this module (keeps tabs/windows in sync when paired
 * with storage events, if desired by the app).
 */
export function persistLanguage(code: string): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, code);
  } catch {
    /* noop */
  }
}

/**
 * Create an isolated i18n instance (for I18nextProvider / SSR / test isolation).
 * Defaults to the detected language (localStorage → navigator → fallback).
 */
export function createI18n(defaultLng?: string): i18n {
  const lng = defaultLng ?? detectInitialLanguage();
  const instance = i18next.createInstance();
  instance.use(initReactI18next).init({
    lng,
    fallbackLng: 'en',
    resources,
    interpolation: { escapeValue: false },
  });
  // Persist on future changes so the next visit keeps the choice.
  instance.on('languageChanged', (newLng) => persistLanguage(newLng));
  return instance;
}

/**
 * Initialize the global i18next singleton (used by useTranslation() without a
 * provider). Call this in test setup or server entry points where
 * I18nextProvider is not available.
 */
export function initGlobalI18n(defaultLng?: string): void {
  if (i18next.isInitialized) return;
  const lng = defaultLng ?? detectInitialLanguage('en');
  i18next.use(initReactI18next).init({
    lng,
    fallbackLng: 'en',
    resources,
    interpolation: { escapeValue: false },
  });
  i18next.on('languageChanged', (newLng) => persistLanguage(newLng));
}

export { useTranslation, Trans, I18nextProvider } from 'react-i18next';
export { LanguageSwitcher } from './LanguageSwitcher';
