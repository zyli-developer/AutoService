import { useEffect, useState } from 'react';
import { useOperatorStore } from './store/operatorStore';
import { LoginPage } from './components/LoginPage';
import { WorkspacePage } from './components/WorkspacePage';

/**
 * On mount, probe ``/api/auth/operator/me`` to detect a pre-existing valid
 * ``operator_session`` cookie (e.g. from a magic-link verify flow). If the
 * server returns 200 we hydrate ``operatorStore`` directly and skip
 * ``LoginPage``; if 401 we fall through to the form. Returns null while
 * the probe is in flight so we never flash the LoginPage on top of an
 * already-authenticated session.
 */
export function App() {
  const isLoggedIn = useOperatorStore((s) => s.isLoggedIn);
  const login = useOperatorStore((s) => s.login);
  const [bootstrapped, setBootstrapped] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (isLoggedIn) {
        setBootstrapped(true);
        return;
      }
      try {
        const r = await fetch('/api/auth/operator/me', {
          credentials: 'include',
        });
        if (!cancelled && r.ok) {
          const ctx = (await r.json()) as { operator_id?: string };
          if (ctx?.operator_id) {
            login(ctx.operator_id, '');
          }
        }
      } catch {
        // Network error → fall through to LoginPage; nothing to swallow loudly.
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // We only ever want the probe to run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!bootstrapped) return null;
  return isLoggedIn ? <WorkspacePage /> : <LoginPage />;
}
