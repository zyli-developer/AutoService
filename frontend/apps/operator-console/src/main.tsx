import React from 'react';
import ReactDOM from 'react-dom/client';
import { I18nextProvider, createI18n } from '@autoservice/i18n';
import { App } from './App';
import './index.css';

const i18n = createI18n();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>
  </React.StrictMode>,
);
