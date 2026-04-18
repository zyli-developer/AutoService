import { useEffect } from 'react';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: Props) {
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
        aria-label="命令面板"
      >
        <div className="cs-cmdk-panel-title">命令面板</div>
        <div>⌘K search is coming soon. Esc to close.</div>
      </div>
    </div>
  );
}
