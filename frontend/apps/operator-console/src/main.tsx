import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { I18nextProvider, createI18n } from '@autoservice/i18n';
import { App } from './App';
import { NoTenantFallback } from './components/NoTenantFallback';
import './index.css';

const i18n = createI18n();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <BrowserRouter>
        <Routes>
          {/* Tenant-scoped entry (T1F.4 / tenant-sandbox design §5.2) */}
          <Route path="/t/:tenantId/operator" element={<App />} />
          {/* Legacy / no-tenant entry — show a helpful fallback */}
          <Route path="/" element={<NoTenantFallback />} />
          {/* Any other path → back to root */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </I18nextProvider>
  </React.StrictMode>,
);
