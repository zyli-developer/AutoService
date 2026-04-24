/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CUSTOMER_CHAT_URL?: string;
  readonly VITE_OPERATOR_CONSOLE_URL?: string;
  readonly VITE_ADMIN_PORTAL_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
