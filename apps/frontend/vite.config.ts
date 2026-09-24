import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
  // the lazily-loaded viewer chunk is essentially three.js itself
  build: { chunkSizeWarningLimit: 600 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
