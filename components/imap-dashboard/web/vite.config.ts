import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: "./",
  build: {
    outDir: "../src/imap_dashboard/ui",
    emptyOutDir: true,
    target: "es2022",
    modulePreload: { polyfill: false },
    cssCodeSplit: false,
    rollupOptions: {
      input: "mail-app.html",
    },
  },
  server: {
    host: "127.0.0.1",
    port: 4178,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
    exclude: ["e2e/**", "node_modules/**"],
  },
});
