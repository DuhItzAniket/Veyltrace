// Vite 8 build and Vitest config (docs/06 §5.1). The dev server binds loopback on the port the
// gateway's CORS list allows (config/gateway.yaml api.cors_origins); no runtime CDN loads.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  preview: { host: "127.0.0.1" },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
