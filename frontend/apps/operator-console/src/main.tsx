import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { I18nextProvider, createI18n } from '@autoservice/i18n';
import { App } from './App';

const i18n = createI18n('zh-CN');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <ConfigProvider>
        <App />
      </ConfigProvider>
    </I18nextProvider>
  </React.StrictMode>,
);
