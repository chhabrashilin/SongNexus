import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the Vite server proxies /api to the FastAPI backend, so the
// browser talks to one origin and no CORS configuration is needed locally.
// 127.0.0.1 (not "localhost"): uvicorn binds IPv4 by default, while "localhost"
// may resolve to ::1 first and reach a different service on the same port.
const apiTarget = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
