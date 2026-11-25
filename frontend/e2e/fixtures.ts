import AxeBuilder from '@axe-core/playwright'
import { test as base, expect, type Page } from '@playwright/test'

import { E2E_PASSWORD } from '../playwright.config.ts'

/** WCAG 2.1 A and AA, the level the app keeps. */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const found = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? 'unknown'}): ${violation.help}\n` +
      violation.nodes.map((node) => `  ${node.target.join(' ')}`).join('\n'),
  )
  expect(found, found.join('\n')).toEqual([])
}

/** `start` is where the app is: `/`, or `./` under a sub-path's baseURL. */
export async function logIn(page: Page, start = '/'): Promise<void> {
  await page.goto(start)
  await page.getByLabel('Password').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
}

/** Every test fails when the browser refuses something under the Content
 * Security Policy, so each screen and dialog the tests reach is checked. */
export const test = base.extend<{ cspViolations: string[] }>({
  cspViolations: [
    async ({ page }, use) => {
      const refused: string[] = []
      page.on('console', (message) => {
        if (message.type() === 'error' && message.text().includes('Content Security Policy')) {
          refused.push(message.text())
        }
      })
      await use(refused)
      expect(refused, refused.join('\n')).toEqual([])
    },
    { auto: true },
  ],
})

export { expect }
