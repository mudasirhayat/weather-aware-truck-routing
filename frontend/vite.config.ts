import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying /api in development keeps the browser same-origin, so CORS and
    // cookie behaviour match production without extra configuration.
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Leaflet and React are large and change far less often than app code;
        // splitting them lets the browser keep them cached across deploys.
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("leaflet")) return "leaflet";
          if (id.includes("react")) return "react";
          return undefined;
        },
      },
    },
  },
});
