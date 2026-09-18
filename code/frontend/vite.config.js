import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The page is served from :3000 and the API listens on :5000, which the browser would
// treat as two different origins and block. Rather than configure CORS, the dev server
// forwards anything starting with /api to Flask, so the browser only ever sees one
// origin and the session cookie just works (decision D4).
//
// "backend" is the docker-compose service name. Running the dev server outside Docker?
// Set VITE_API_PROXY_TARGET=http://localhost:5001 in your shell.
const apiTarget = process.env.VITE_API_PROXY_TARGET || "http://backend:5000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true
      }
    },
    watch: {
      // Bind-mounted files on macOS and Windows don't emit change events the way
      // native ones do; without polling, saving a file doesn't reload the page.
      usePolling: true
    }
  }
});
