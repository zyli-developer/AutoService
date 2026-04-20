import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES } from './index';

export interface LanguageSwitcherProps {
  /** Optional override for the className (lets each app style it). */
  className?: string;
  /** Optional inline style override. */
  style?: React.CSSProperties;
  /** Optional data-testid. Defaults to "language-switch". */
  testId?: string;
}

/**
 * Drop-in `<select>` that changes the active language via i18next and
 * persists the choice (via the languageChanged listener in createI18n).
 *
 * The label shown in each option is the language's nativeLabel so the
 * switcher is always legible regardless of the current UI language.
 */
export function LanguageSwitcher({
  className,
  style,
  testId = 'language-switch',
}: LanguageSwitcherProps) {
  const { i18n } = useTranslation();

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    i18n.changeLanguage(e.target.value);
  };

  return (
    <select
      data-testid={testId}
      value={i18n.language}
      onChange={handleChange}
      className={className}
      style={style}
    >
      {SUPPORTED_LANGUAGES.map((lang) => (
        <option key={lang.code} value={lang.code}>
          {lang.nativeLabel}
        </option>
      ))}
    </select>
  );
}
