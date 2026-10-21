import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

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

export async function logIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Password').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
}

export { expect, test } from '@playwright/test'
