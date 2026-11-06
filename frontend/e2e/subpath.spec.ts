import { expect, logIn, test } from './fixtures.ts'

// The same app and database, served by nginx at /brzask/ with BASE_URL set.
const PREFIX = '/brzask/'

test('the app works under a sub-path', async ({ page }) => {
  const failed: string[] = []
  page.on('response', (response) => {
    if (response.status() >= 400) failed.push(`${String(response.status())} ${response.url()}`)
  })

  await logIn(page, './')
  expect(new URL(page.url()).pathname).toBe(PREFIX)
  const cards = page.locator('[data-slot="card"]')
  await expect(cards).toHaveCount(7)

  const openUrl = await cards.first().getByRole('link').first().getAttribute('href')
  expect(openUrl).toMatch(/^\/brzask\/open\?id=\d+&sig=/)
  const opened = await page.request.get(openUrl ?? '', { maxRedirects: 0 })
  expect(opened.status()).toBe(302)

  await page.getByRole('link', { name: 'Archive' }).click()
  await page.getByRole('main').getByRole('link').nth(1).click()
  await expect(page.getByRole('heading', { name: /^Digest of / })).toBeVisible()
  expect(new URL(page.url()).pathname).toMatch(/^\/brzask\/archive\/\d{4}-\d{2}-\d{2}$/)
  // A deep link loaded afresh: its bundles resolve against the <base> element.
  await page.reload()
  await expect(page.getByRole('heading', { name: /^Digest of / })).toBeVisible()

  const scope = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    return { scope: registration.scope, state: registration.active?.state }
  })
  expect(scope).toEqual({ scope: new URL(PREFIX, page.url()).href, state: 'activated' })

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page.getByLabel('Password')).toBeVisible()
  expect(failed).toEqual([])
})
