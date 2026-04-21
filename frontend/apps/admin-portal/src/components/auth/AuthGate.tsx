/**
 * T6F.2 · AuthGate — magic-link auth wrapper
 *
 * Wraps the admin-portal root. Consumes `useSessionMode` and either:
 *   - `loading`   → renders `<Splash />` (flicker mitigation, spec §9)
 *   - `error`     → renders `<Splash variant="error" />` with a retry button
 *   - unauthenticated → triggers a browser-level redirect to
 *     `/login?redirect=<path>` and renders Splash until unmount.
 *   - authenticated   → renders `children`
 *
 * Implementation note: AuthGate uses `window.location.assign` (hard
 * redirect) instead of React Router's `<Navigate>` so it can run outside
 * any `<Router>` context — MasterLayout / TenantLayout already own their
 * own `<BrowserRouter>`, and a second one at the App level would trigger
 * React Router v6's "You cannot render a <Router> inside another <Router>"
 * guard. Hard redirect is also semantically correct: the magic-link verify
 * flow does a server-side 302, so the SPA has no state worth preserving
 * across login.
 *
 * A `redirector` prop is accepted for tests to capture the navigation
 * target without actually unloading the jsdom page.
 *
 * Key invariant (spec §9): never render anon content between `loading`
 * and the redirect. The Splash frame covers the network gap so the user
 * never sees a bare page flash before the login redirect.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5, §9
 */
import { useEffect, type ReactNode } from 'react';
import { useSessionMode } from '@autoservice/shared';

interface AuthGateProps {
  children: ReactNode;
  /** Test seam — called with the target URL on anon redirect. */
  redirector?: (to: string) => void;
}

function defaultRedirector(to: string) {
  if (typeof window !== 'undefined') {
    window.location.assign(to);
  }
}

function Splash({
  variant = 'loading',
  message,
  onRetry,
}: {
  variant?: 'loading' | 'error';
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      data-testid="auth-splash"
      data-variant={variant}
      role={variant === 'error' ? 'alert' : 'status'}
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        color: '#24292f',
        background:
          'radial-gradient(ellipse at top, #f0f6ff 0%, #ffffff 60%)',
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div
        aria-hidden="true"
        style={{
          width: 48,
          height: 48,
          borderRadius: '50%',
          border: '3px solid #d0d7de',
          borderTopColor: variant === 'error' ? '#cf222e' : '#0969da',
          animation:
            variant === 'loading'
              ? 'authgate-spin 0.9s linear infinite'
              : 'none',
        }}
      />
      <div style={{ fontWeight: 600, fontSize: 18 }}>AutoService</div>
      {message ? (
        <div style={{ color: '#57606a', fontSize: 13 }}>{message}</div>
      ) : null}
      {variant === 'error' && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          data-testid="auth-splash-retry"
          style={{
            marginTop: 4,
            padding: '6px 14px',
            borderRadius: 6,
            border: '1px solid #d0d7de',
            background: '#ffffff',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          Retry
        </button>
      ) : null}
      <style>{'@keyframes authgate-spin{to{transform:rotate(360deg)}}'}</style>
    </div>
  );
}

export function AuthGate({ children, redirector }: AuthGateProps) {
  const { data, loading, error, refetch } = useSessionMode();
  const shouldRedirect = !loading && !error && (!data || !data.authenticated);

  useEffect(() => {
    if (!shouldRedirect) return;
    const nav = redirector ?? defaultRedirector;
    const pathname =
      typeof window !== 'undefined' ? window.location.pathname : '/';
    const search =
      typeof window !== 'undefined' ? window.location.search : '';
    const target = `${pathname}${search}`;
    nav(`/login?redirect=${encodeURIComponent(target)}`);
  }, [shouldRedirect, redirector]);

  if (loading) {
    return <Splash variant="loading" />;
  }

  if (error) {
    return (
      <Splash
        variant="error"
        message="Session check failed — retry to continue."
        onRetry={refetch}
      />
    );
  }

  if (!data || !data.authenticated) {
    // While the useEffect fires, keep showing Splash so anon content never
    // flashes (spec §9).
    return <Splash variant="loading" message="Redirecting to sign-in…" />;
  }

  return <>{children}</>;
}
