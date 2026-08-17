import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/assist": "http://127.0.0.1:8000",
      "/tools": "http://127.0.0.1:8000",
      "/agent": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
