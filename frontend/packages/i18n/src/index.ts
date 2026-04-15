import i18next, { type i18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zhCN from './locales/zh-CN.json';

/**
 * T1B.6 将扩展为 22 语种 + namespace 懒加载。
 * 当前骨架：en 为兜底，zh-CN 为默认。
 */
export function createI18n(defaultLng: string = 'zh-CN'): i18n {
  const instance = i18next.createInstance();
  instance.use(initReactI18next).init({
    lng: defaultLng,
    fallbackLng: 'en',
    resources: {
      en: { translation: en },
      'zh-CN': { translation: zhCN },
    },
    interpolation: { escapeValue: false },
  });
  return instance;
}

export { useTranslation, Trans, I18nextProvider } from 'react-i18next';
