import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    // Development only. In production Caddy serves dist/ and routes /api to
    // FastAPI, so the browser continues to use the same relative API URLs.
    host: "127.0.0.1",
    allowedHosts: ["localhost", "127.0.0.1", ".ngrok-free.app", ".ngrok-free.dev"],
    proxy: {
      "/api": process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000",
    },
  },
});
