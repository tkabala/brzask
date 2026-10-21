// The README's screenshot and demo GIF, taken from the end-to-end stack
// (deploy/compose.yaml filled by `brzask seed-demo`): `just media`.
// Needs ffmpeg for the GIF.
import { execFileSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium, type Page } from '@playwright/test'

import startStack from '../e2e/global-setup.ts'
import { APP_PORT, E2E_PASSWORD } from '../playwright.config.ts'

const BASE = `http://localhost:${String(APP_PORT)}`
const ASSETS = fileURLToPath(new URL('../../docs/assets/', import.meta.url))
const VIEWPORT = { width: 1000, height: 720 }

/** The tour: each step leaves the page as one frame of the GIF, shown for `seconds`. */
const STEPS: { seconds: number; act: (page: Page) => Promise<unknown> }[] = [
  { seconds: 2.5, act: () => Promise.resolve() },
  {
    seconds: 3,
    act: async (page) => {
      await page.getByRole('button', { name: 'Why here?' }).nth(3).click()
      await page.getByRole('region', { name: 'How it got here' }).waitFor()
    },
  },
  {
    seconds: 2,
    act: async (page) => {
      await page.getByRole('link', { name: 'Archive' }).click()
      await page.getByRole('heading', { name: 'Archive', level: 1 }).waitFor()
    },
  },
  {
    seconds: 2.5,
    act: async (page) => {
      await page.getByRole('main').getByRole('link').nth(2).click()
      await page.getByRole('heading', { name: /^Digest of / }).waitFor()
    },
  },
  {
    seconds: 3,
    act: async (page) => {
      await page.getByRole('link', { name: 'Sources' }).click()
      await page.getByRole('region', { name: 'Waiting for a decision' }).waitFor()
    },
  },
  {
    seconds: 3,
    act: async (page) => {
      await page.getByRole('link', { name: 'Interests' }).click()
      await page.getByRole('heading', { name: 'Interests', level: 1 }).waitFor()
    },
  },
]

const stopStack = startStack()
const frames = await mkdtemp(join(tmpdir(), 'brzask-media-'))
try {
  const browser = await chromium.launch()
  const context = await browser.newContext({
    locale: 'en-US',
    timezoneId: 'UTC',
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()
  await page.goto(BASE)
  await page.getByLabel('Password').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.getByRole('heading', { name: 'Today', level: 1 }).waitFor()
  await page.waitForLoadState('networkidle')
  await page.screenshot({ path: join(ASSETS, 'screenshot.png') })

  // ffmpeg's concat list: each frame with how long it stays; the last is repeated
  // because the list format drops the last duration.
  const list: string[] = []
  for (const [n, step] of STEPS.entries()) {
    await step.act(page)
    await page.waitForLoadState('networkidle')
    const frame = join(frames, `${String(n)}.png`)
    await page.screenshot({ path: frame })
    list.push(`file '${frame}'`, `duration ${String(step.seconds)}`)
  }
  list.push(list.at(-2) ?? '')
  await browser.close()
  await writeFile(join(frames, 'frames.txt'), list.join('\n') + '\n')

  // One palette for every frame keeps the colours stable and the file small.
  const filters =
    'scale=800:-1:flags=lanczos,split[a][b];' +
    '[a]palettegen=max_colors=64:stats_mode=full[p];' +
    '[b][p]paletteuse=dither=none'
  execFileSync('ffmpeg', [
    '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', join(frames, 'frames.txt'),
    '-vf', filters, join(ASSETS, 'demo.gif'),
  ]) // prettier-ignore
} finally {
  await rm(frames, { recursive: true, force: true })
  stopStack()
}
