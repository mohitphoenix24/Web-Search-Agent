import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true, // fail loudly instead of silently picking another port
    // Polling instead of OS file watchers, so it also works on machines that
    // run out of inotify watchers (Vite crashes with ENOSPC there).
    watch: { usePolling: true, interval: 300 },
    // Any request to /api/... is forwarded to the Python backend.
    // This way the browser only talks to one address (no CORS issues).
    proxy: { "/api": "http://localhost:8000" },
  },
});
