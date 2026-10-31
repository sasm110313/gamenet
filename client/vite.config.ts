import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The renderer is packaged and loaded from file://. Never point it at a dev
// server at runtime, and never let it fetch remote assets: Windows 7 clients
// must work with the LAN unplugged from the internet.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    target: "chrome108",
    outDir: "dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
});
