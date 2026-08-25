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
      // Port 8000 is commonly occupied by other local tools. Keep this
      // project's development API on 8001; production still uses Caddy and
      // the Docker-internal api:8000 address.
      "/api": process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8001",
    },
  },
});
