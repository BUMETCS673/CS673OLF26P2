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
  },
  test: {
    // Read only when coverage is on, which CI turns on with --coverage.enabled; the v8
    // provider is the @vitest/coverage-v8 devDependency. See the "Unit tests with
    // coverage" step in .github/workflows/ci.yml.
    //
    // AI Utilization: ~100% of this block
    // AI Tools Used: Claude Code (Claude Opus 5.5)
    // AI-Assisted Activities:
    //   CI configuration
    // Human role: direction and review by Duc Anh Nguyen.
    coverage: {
      provider: "v8",
      include: ["src/**"],
      reporter: ["text", "json-summary"],
      thresholds: {
        // Same floor as the backend's --cov-fail-under=90.
        lines: 90,
        statements: 90
      }
    }
  }
});
