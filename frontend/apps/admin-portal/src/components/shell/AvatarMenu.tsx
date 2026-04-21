import { useState, useEffect, useRef } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

/**
 * T6F.4 — default redirector matches batch-9 AuthGate pattern.
 * See: frontend/apps/admin-portal/src/components/auth/AuthGate.tsx
 */
function defaultRedirector(to: string) {
  if (typeof window !== 'undefined') {
    window.location.assign(to);
  }
}

interface AvatarMenuProps {
  /**
   * Test seam — called with the target URL after logout. Defaults to
   * `window.location.assign`. Matches AuthGate's redirector injection so
   * tests can intercept without unloading jsdom.
   */
  redirector?: (to: string) => void;
}

export function AvatarMenu({ redirector }: AvatarMenuProps = {}) {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const logout = useAdminStore((s) => s.logout);
  const [open, setOpen] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const initial = tenantId ? tenantId.charAt(0).toLowerCase() : '?';
  const nav = redirector ?? defaultRedirector;

  async function handleLogout() {
    if (logoutPending) return;
    setLogoutPending(true);
    // Clear in-memory admin state defensively (zustand); batch-9 tests
    // assert `useAdminStore.getState().isLoggedIn === false` after click.
    logout();
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // Best-effort: the cookie is HttpOnly so the backend is the only
      // thing that can truly revoke the session. If the network call fails
      // we still redirect to /login; AuthGate will re-probe the session
      // and show its error splash on the next load if needed.
    } finally {
      setOpen(false);
      nav('/login');
      // Leave `logoutPending` true — the page is about to navigate; flipping
      // it back would let the user click Logout again during the redirect,
      // which is pointless and could race.
    }
  }

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="cs-avatar-btn"
        data-testid="avatar-trigger"
        aria-label={t('admin.user_menu.open')}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {initial}
      </button>
      {open && (
        <div className="cs-avatar-menu" data-testid="avatar-menu" role="menu">
          <div className="cs-avatar-menu-row label">{t('admin.user_menu.tenant_id')}</div>
          <div className="cs-avatar-menu-row value" data-testid="tenant-id">
            {tenantId ?? '—'}
          </div>
          <div style={{ height: 1, background: 'var(--glass-border)', margin: '4px 0' }} />
          <button
            type="button"
            className="cs-avatar-menu-btn"
            data-testid="btn-logout"
            onClick={handleLogout}
            disabled={logoutPending}
            aria-busy={logoutPending}
          >
            {t('common.logout')}
          </button>
          <div className="cs-avatar-menu-row label" style={{ marginTop: 4 }}>{t('admin.user_menu.version')}</div>
          <div className="cs-avatar-menu-row value">v0.0.1</div>
        </div>
      )}
    </div>
  );
}
