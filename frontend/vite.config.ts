import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    // The ngrok tunnel targets IPv4 explicitly; do not leave an old IPv6 Vite
    // process on the same port for localhost to resolve to.
    host: "127.0.0.1",
    allowedHosts: ["shopper-washable-crock.ngrok-free.dev"],
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
