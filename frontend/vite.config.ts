import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

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
  ],
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
    css: false,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/routeTree.gen.ts', 'src/test/**', 'src/**/*.test.{ts,tsx}'],
      reporter: ['text', 'lcov'],
    },
  },
})
