import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

import { NOT_THE_APP } from './src/lib/sw-routes.ts'

const { version } = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
) as {
  version: string
}

// The icon's own background: the installed app's splash screen and title bar.
const ICON_BACKGROUND = '#171717'

export default defineConfig({
  plugins: [
    // Must run before the React plugin so generated routes are compiled.
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
      routeFileIgnorePattern: '\\.test\\.tsx?$',
    }),
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      // Behind a proxy with basic or forward auth the manifest needs the login too.
      useCredentials: true,
      manifest: {
        name: 'brzask',
        short_name: 'brzask',
        description: 'A calm, finite, personal news digest: exactly 7 articles a day.',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        theme_color: ICON_BACKGROUND,
        background_color: ICON_BACKGROUND,
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // Only the app itself; its data is saved by the app (src/lib/offline-cache.ts).
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        navigateFallback: 'index.html',
        navigateFallbackDenylist: NOT_THE_APP,
      },
      devOptions: { enabled: false },
    }),
  ],
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // The API in development: `just api` (or `brzask api`) on port 8000.
    proxy: Object.fromEntries(
      ['/api', '/open', '/healthz', '/readyz'].map((path) => [
        path,
        { target: process.env.BRZASK_API ?? 'http://127.0.0.1:8000' },
      ]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright runs e2e/ against the real API.
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/routeTree.gen.ts', 'src/test/**', 'src/**/*.test.{ts,tsx}'],
      reporter: ['text', 'lcov'],
    },
  },
})
