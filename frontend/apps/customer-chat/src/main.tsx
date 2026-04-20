import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { I18nextProvider, createI18n } from '@autoservice/i18n';
import { App } from './App';
import './index.css';

const i18n = createI18n();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <BrowserRouter>
        <Routes>
          {/* Canonical tenant-scoped route — see spec §5.2 */}
          <Route path="/t/:tenantId/chat" element={<App />} />
          {/* Fork-side fallback: /chat with or without ?tenant=<id> — §5.4 */}
          <Route path="/chat" element={<App />} />
          {/* Legacy/root entrypoint — shows tenant-selection fallback UI */}
          <Route path="*" element={<App />} />
        </Routes>
      </BrowserRouter>
    </I18nextProvider>
  </React.StrictMode>,
);
