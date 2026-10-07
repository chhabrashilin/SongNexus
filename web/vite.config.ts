import react from '@vitejs/plugin-react';
import {defineConfig} from 'vitest/config';

// The dev server proxies /v1 to the API so the browser sees one origin.
// 127.0.0.1 (not "localhost"): uvicorn binds IPv4, and "localhost" may resolve
// to ::1 first and reach a different service on the same port. Port 8790 is
// SongNexus's local API port, chosen to avoid common dev ports (8000, 8080).
const apiTarget = process.env.SONGNEXUS_API ?? 'http://127.0.0.1:8790';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/v1': {target: apiTarget, changeOrigin: true},
      '/healthz': {target: apiTarget, changeOrigin: true},
    },
  },
  build: {sourcemap: true},
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
