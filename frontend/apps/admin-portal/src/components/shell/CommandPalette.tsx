import { useEffect } from 'react';
import { useTranslation } from '@autoservice/i18n';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: Props) {
  const { t } = useTranslation();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      {/* Click-outside dismiss surface as a real <button> so keyboard users
          can also Tab onto it (Esc still works via the global keydown above). */}
      <button
        type="button"
        className="cs-cmdk-overlay"
        data-testid="cmdk-overlay"
        aria-label={t('admin.command_palette.close')}
        onClick={onClose}
      />
      <div
        className="cs-cmdk-panel"
        data-testid="cmdk-panel"
        role="dialog"
        aria-label={t('admin.command_palette.title')}
      >
        <div className="cs-cmdk-panel-title">{t('admin.command_palette.title')}</div>
        <div>{t('admin.command_palette.placeholder')}</div>
      </div>
    </>
  );
}
