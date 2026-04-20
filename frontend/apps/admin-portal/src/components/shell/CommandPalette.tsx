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
    <div className="cs-cmdk-overlay" data-testid="cmdk-overlay" onClick={onClose}>
      <div
        className="cs-cmdk-panel"
        data-testid="cmdk-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={t('admin.command_palette.title')}
      >
        <div className="cs-cmdk-panel-title">{t('admin.command_palette.title')}</div>
        <div>{t('admin.command_palette.placeholder')}</div>
      </div>
    </div>
  );
}
