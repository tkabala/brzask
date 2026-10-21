import { defineConfig, devices } from '@playwright/test'

const API_PORT = 8100
const APP_PORT = 4173

/** The test password and its argon2 hash; both only ever used here. */
export const E2E_PASSWORD = 'e2e-password'
const E2E_PASSWORD_HASH =
  '$argon2id$v=19$m=65536,t=3,p=4$q1BsQc7/PzOIWWGDnumVUQ$ZvbWoxjVF1/fTCTbvqLS11UQQIFvV/73uDDZglryrvg'

export default defineConfig({
  testDir: './e2e',
  // The tests share one database and change it, so they run one after another.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${String(APP_PORT)}`,
    trace: 'retain-on-failure',
    locale: 'en-US',
    timezoneId: 'UTC',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: './e2e/start-api.sh',
      url: `http://127.0.0.1:${String(API_PORT)}/readyz`,
      env: {
        E2E_API_PORT: String(API_PORT),
        AUTH_MODE: 'password',
        AUTH_PASSWORD_HASH: E2E_PASSWORD_HASH,
        AUTH_SESSION_SECRET: 'e2e-session-secret-of-at-least-32-chars',
        LOG_FORMAT: 'json',
      },
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      // The production build, as people get it; preview proxies the API.
      command: `pnpm build && pnpm exec vite preview --port ${String(APP_PORT)} --strictPort`,
      url: `http://localhost:${String(APP_PORT)}`,
      env: { BRZASK_API: `http://127.0.0.1:${String(API_PORT)}` },
      timeout: 180_000,
      reuseExistingServer: false,
    },
  ],
})
