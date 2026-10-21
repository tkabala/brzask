import { expect, expectAccessible, logIn, test } from './fixtures.ts'

test('the login refuses a wrong password, then shows today’s digest', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
  await expectAccessible(page)

  await page.getByLabel('Password').fill('wrong')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText('Wrong password.')).toBeVisible()

  await logIn(page)
  await expect(page.locator('[data-slot="card"]')).toHaveCount(7)
})

const SCREENS = [
  ['/', 'Today'],
  ['/archive', 'Archive'],
  ['/search', 'Search'],
  ['/sources', 'Sources'],
  ['/interests', 'Interests'],
  ['/status', 'Status'],
] as const

for (const [path, heading] of SCREENS) {
  test(`${heading} has no accessibility violations`, async ({ page }) => {
    await logIn(page)
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
    // Wait for the data, so axe checks the filled page.
    await page.waitForLoadState('networkidle')
    await expectAccessible(page)
  })
}

test('an archived day, with why an article is there', async ({ page }) => {
  await logIn(page)
  await page.getByRole('link', { name: 'Archive' }).click()
  await page.getByRole('main').getByRole('link').nth(1).click()
  await expect(page.getByRole('heading', { name: /^Digest of / })).toBeVisible()

  await page.getByRole('button', { name: 'Why here?' }).first().click()
  const breakdown = page.getByRole('region', { name: 'How it got here' })
  await expect(breakdown).toContainText('The day started with 200 articles')
  await expect(breakdown).toContainText('Ranked 2 of 40 candidates')
  await expectAccessible(page)
})

test('opening an article goes through /open and is remembered', async ({ page }) => {
  await logIn(page)
  const card = page.locator('[data-slot="card"]').first()
  await expect(card.getByText('Opened')).toHaveCount(0)

  // The tab follows /open's redirect to a made-up host; what counts is the redirect.
  const [redirect] = await Promise.all([
    page.context().waitForEvent('response', (response) => response.url().includes('/open?')),
    card.getByRole('link').first().click(),
  ])
  expect(redirect.status()).toBe(302)
  expect(await redirect.headerValue('location')).toMatch(/^https:\/\/postgres-weekly\.example\//)
  await expect(card.getByText('Opened')).toBeVisible()

  await page.reload()
  await expect(page.locator('[data-slot="card"]').first().getByText('Opened')).toBeVisible()
})

test('a pending source is approved', async ({ page }) => {
  await logIn(page)
  await page.goto('/sources')
  const pending = page.getByRole('region', { name: 'Waiting for a decision' })
  await pending.getByRole('button', { name: 'Read it: Query Planner Blog' }).click()

  await expect(pending.getByText('Query Planner Blog')).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'All sources' }).getByText('Query Planner Blog'),
  ).toBeVisible()
})

test('reader notes are saved', async ({ page }) => {
  await logIn(page)
  await page.goto('/interests')
  await page.getByRole('button', { name: 'Edit: Homelab' }).click()
  const form = page.getByRole('form', { name: 'Homelab' })
  await form.getByLabel('Reader notes').fill('want: backup stories')
  await form.getByRole('button', { name: 'Save' }).click()

  await page.reload()
  await expect(page.getByText('want: backup stories')).toBeVisible()
})

test('the digest is paused and resumed', async ({ page }) => {
  await logIn(page)
  await page.goto('/status')
  await page.getByLabel('Pause until').fill('2099-01-01')
  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByText(/The digest is paused until/)).toBeVisible()
  await expectAccessible(page)

  await page.getByRole('button', { name: 'Resume now' }).click()
  await expect(page.getByText('The digest runs every day.')).toBeVisible()
})

test('logging out leads back to the login', async ({ page }) => {
  await logIn(page)
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page.getByLabel('Password')).toBeVisible()
  await page.goto('/status')
  await expect(page.getByLabel('Password')).toBeVisible()
})
