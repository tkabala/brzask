import { defineConfig, devices } from '@playwright/test'

/** Where the compose stack (e2e/stack.sh) publishes the app. */
export const APP_PORT = 8100
/** Where nginx serves the same app under /brzask/ (e2e/compose.yaml). */
export const SUBPATH_PORT = 8101

/** The test password and its argon2 hash; both only ever used here. */
export const E2E_PASSWORD = 'e2e-password'
export const E2E_PASSWORD_HASH =
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
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, testIgnore: /subpath\.spec/ },
    {
      name: 'subpath',
      testMatch: /subpath\.spec/,
      use: {
        ...devices['Desktop Chrome'],
        // Paths in this project are relative ('./', 'archive'), so they keep the prefix.
        baseURL: `http://localhost:${String(SUBPATH_PORT)}/brzask/`,
      },
    },
  ],
  // The app as people run it: deploy/compose.yaml on an image of this checkout.
  globalSetup: './e2e/global-setup.ts',
})
