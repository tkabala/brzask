import { expect, expectAccessible, logIn, test } from './fixtures.ts'

test('the login refuses a wrong password, then shows today’s digest', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()

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
  ['/changes', 'Changes'],
  ['/status', 'Status'],
] as const

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`in the ${colorScheme} theme`, () => {
    test.use({ colorScheme })

    test.beforeEach(async ({ page }) => {
      await page.goto('/')
      // Axe must judge the theme it is named after.
      const html = page.locator('html')
      await (colorScheme === 'dark'
        ? expect(html).toHaveClass(/\bdark\b/)
        : expect(html).not.toHaveClass(/\bdark\b/))
    })

    test('the login has no accessibility violations', async ({ page }) => {
      await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
      await expectAccessible(page)

      // An error's colour too, without a wrong password counting towards a lockout.
      await page.getByRole('button', { name: 'Log in' }).click()
      await expect(page.getByText('Enter the password.')).toBeVisible()
      await expectAccessible(page)
    })

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

    test('the open ranking explanation has no accessibility violations', async ({ page }) => {
      await logIn(page)
      await page.getByRole('button', { name: 'Why here?' }).first().click()
      await expect(page.getByRole('region', { name: 'How it got here' })).toBeVisible()
      await expectAccessible(page)
    })
  })
}

test.describe('choosing a theme', () => {
  test.use({ colorScheme: 'light' })

  test('the choice survives a reload and overrides the system', async ({ page }) => {
    await logIn(page)
    const html = page.locator('html')
    await expect(html).not.toHaveClass(/\bdark\b/)

    await page.getByLabel('Theme').selectOption('dark')
    await expect(html).toHaveClass(/\bdark\b/)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
    await expect(html).toHaveClass(/\bdark\b/)
    await expect(page.getByLabel('Theme')).toHaveValue('dark')
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0a0a0a')
  })

  test('the system theme follows the operating system while open', async ({ page }) => {
    await page.goto('/')
    const html = page.locator('html')
    await expect(html).not.toHaveClass(/\bdark\b/)

    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(html).toHaveClass(/\bdark\b/)
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0a0a0a')
  })

  test('a stored theme is on the page before any bundled script runs', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('brzask-theme', 'dark')
    })
    let blocked = 0
    await page.route('**/*.js', (route) => {
      blocked += 1
      return route.abort()
    })

    await page.goto('/')

    expect(blocked).toBeGreaterThan(0)
    await expect(page.locator('html')).toHaveClass(/\bdark\b/)
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0a0a0a')
  })
})

test('an archived day, with why an article is there', async ({ page }) => {
  await logIn(page)
  await page.getByRole('link', { name: 'Archive' }).click()
  await page.getByRole('main').getByRole('link').nth(1).click()
  await expect(page.getByRole('heading', { name: /^Digest of / })).toBeVisible()

  await page.getByRole('button', { name: 'Why here?' }).first().click()
  const breakdown = page.getByRole('region', { name: 'How it got here' })
  // Yesterday in the demo instance: its run started with 187 candidates.
  await expect(breakdown).toContainText('The day started with 187 articles')
  await expect(breakdown).toContainText('Ranked 1 of 40 candidates')
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
  expect(await redirect.headerValue('location')).toMatch(/^https:\/\/[a-z-]+\.example\//)
  await expect(card.getByText('Opened')).toBeVisible()

  await page.reload()
  await expect(page.locator('[data-slot="card"]').first().getByText('Opened')).toBeVisible()
})

test('a pending source is approved', async ({ page }) => {
  await logIn(page)
  await page.goto('/sources')
  const pending = page.getByRole('region', { name: 'Waiting for a decision' })
  await pending.getByRole('button', { name: 'Read it: Planner Notes' }).click()

  await expect(pending.getByText('Planner Notes')).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'All sources' }).getByText('Planner Notes'),
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

test('the app can be installed', async ({ page, request }) => {
  const manifest = (await (await request.get('/manifest.webmanifest')).json()) as {
    name: string
    display: string
    start_url: string
    icons: { sizes: string; purpose?: string }[]
  }
  expect(manifest).toMatchObject({ name: 'brzask', display: 'standalone', start_url: './' })
  const sizes = manifest.icons.map((icon) => icon.sizes)
  expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']))
  expect(manifest.icons.some((icon) => icon.purpose === 'maskable')).toBe(true)

  await logIn(page)
  const state = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    return registration.active?.state
  })
  expect(state).toBe('activated')
})

test('today’s digest is readable offline, until logging out', async ({ page, context }) => {
  await logIn(page)
  const cards = page.locator('[data-slot="card"]')
  await expect(cards).toHaveCount(7)
  const openUrl = await cards.first().getByRole('link').first().getAttribute('href')
  // The service worker takes over this page, and the copy is written.
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null)
  await page.waitForFunction(() => localStorage.getItem('brzask-cache')?.includes('"articles"'))

  await context.setOffline(true)
  await page.reload()
  await expect(cards).toHaveCount(7)
  await expect(page.getByRole('status')).toContainText("You're offline")
  await expect(page.getByText(/^Saved at /)).toBeVisible()
  await expectAccessible(page)

  // Any other page opens in the app, and says it needs a connection.
  await page.goto('/archive/2026-10-01')
  await expect(page.getByText('This page needs a connection.')).toBeVisible()
  // An article link is the API's, never the app's.
  await expect(page.goto(openUrl ?? '/open')).rejects.toThrow()

  await context.setOffline(false)
  await page.goto('/')
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page.getByLabel('Password')).toBeVisible()
  await context.setOffline(true)
  await page.reload()
  await expect(page.getByRole('status')).toBeVisible()
  await expect(cards).toHaveCount(0)
})
