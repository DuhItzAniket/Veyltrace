/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Gateway origin for the dev server, e.g. http://127.0.0.1:8030; default http://127.0.0.1:8000. */
  readonly VITE_GATEWAY_ORIGIN?: string;
}
