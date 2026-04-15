import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useWebSocket } from './hooks/useWebSocket';

export function App() {
  const { t } = useTranslation();
  const { status, lastFrame } = useWebSocket('ws://localhost:9999/ws/customer');
  const [ticks, setTicks] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTicks((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <main className="flex h-full flex-col items-center justify-center gap-4 bg-slate-50 p-6 text-slate-800">
      <h1 className="text-2xl font-semibold">{t('app.title')} · customer-chat</h1>
      <p className="text-sm text-slate-500">{t('app.placeholder')}</p>
      <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">WS</span>
          <span className={status === 'open' ? 'text-emerald-600' : 'text-slate-400'}>{status}</span>
        </div>
        <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-600">
          {lastFrame ? JSON.stringify(lastFrame, null, 2) : `uptime: ${ticks}s`}
        </pre>
      </section>
      <p className="text-xs text-slate-400">T1B.1-6 TODO</p>
    </main>
  );
}
