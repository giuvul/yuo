/// <reference types="vitest/config" />
import { lingui } from "@lingui/vite-plugin";
import babel from "@rolldown/plugin-babel";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// The installable app: vite-plugin-pwa with our own Workbox service worker (sw/sw.ts,
// injectManifest). It precaches the shell and the built static assets only; `/api` is never cached.
// Colours follow tokens.css (accent, light background).
const pwa = VitePWA({
  strategies: "injectManifest",
  srcDir: "sw",
  filename: "sw.ts",
  registerType: "prompt",
  injectRegister: false, // src/pwa/pwa.ts registers it (built mode only) and shows "Reload to update"
  includeAssets: ["icon.svg", "favicon.svg", "favicon.ico", "apple-touch-icon.png"],
  manifest: {
    name: "Yuo",
    short_name: "Yuo",
    description: "Your own learning paths, lessons, practice and tutor.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    theme_color: "#1E3B2F",
    background_color: "#F7F8F3",
    icons: [
      { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  },
  injectManifest: {
    globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
    globIgnores: ["**/*.map"],
  },
  devOptions: { enabled: false },
});

// Lingui on Vite 8 (Rolldown): @vitejs/plugin-react 6 no longer runs Babel, so the
// Lingui macro runs through @rolldown/plugin-babel. @lingui/vite-plugin compiles
// imported .po catalogs to JS on the fly (lazy-loaded per locale).
export default defineConfig({
  plugins: [
    babel({
      include: /\/src\/.*\.[jt]sx?$/,
      plugins: ["@lingui/babel-plugin-lingui-macro"],
    }),
    react(),
    lingui(),
    pwa,
  ],
  // `uv run scripts/dev.py` runs the API on 18765; one origin in dev as in production. The browser
  // tests point it at their own backend (YUO_API_URL); `vite preview` uses the same proxy.
  server: {
    proxy: { "/api": process.env["YUO_API_URL"] ?? "http://127.0.0.1:18765" },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
  css: {
    modules: {
      localsConvention: "camelCaseOnly",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
});
