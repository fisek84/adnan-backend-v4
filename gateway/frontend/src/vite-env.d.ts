/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PWA_SW_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
