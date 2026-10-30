import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import seoPlugin from "./seo/vitePlugin";
import { DEFAULT_SITE_URL } from "./src/seo/siteSeo";

const siteUrl = (process.env.SITE_URL || DEFAULT_SITE_URL).replace(/\/+$/, "");

export default defineConfig({
  plugins: [react(), seoPlugin(siteUrl)],
  define: { __SITE_URL__: JSON.stringify(siteUrl) },
  resolve: { dedupe: ["react", "react-dom"] },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/v1": { target: process.env.API_URL ?? "http://127.0.0.1:8000", changeOrigin: true },
      "/socket.io": { target: process.env.API_URL ?? "http://127.0.0.1:8000", changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
        },
      },
    },
  },
});
