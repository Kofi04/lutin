import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One HTML page per Tauri window (DESIGN.md section 2).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true, // Tauri's devUrl and the core's Origin list expect it
    host: "127.0.0.1",
    fs: { allow: [resolve(import.meta.dirname, "..")] }, // the shared protocol JSON
  },
  build: {
    target: "es2022",
    rollupOptions: {
      input: {
        avatar: resolve(import.meta.dirname, "avatar.html"),
        panel: resolve(import.meta.dirname, "panel.html"),
        overlay: resolve(import.meta.dirname, "overlay.html"),
      },
    },
  },
});
