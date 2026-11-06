import { useSyncExternalStore } from 'react'

import { browserStorage } from '@/lib/offline-cache'

export const THEMES = ['system', 'light', 'dark'] as const
export type Theme = (typeof THEMES)[number]

export const THEME_KEY = 'brzask-theme'

/** The browser's bar over the page: `--background` of each theme in src/index.css. */
export const THEME_COLORS = { light: '#ffffff', dark: '#0a0a0a' } as const

const DARK_SYSTEM = '(prefers-color-scheme: dark)'

function isTheme(value: string | null | undefined): value is Theme {
  return (THEMES as readonly (string | null | undefined)[]).includes(value)
}

/** The stored choice; the system's preference without one, or where storage is blocked. */
export function readStoredTheme(): Theme {
  try {
    const stored = browserStorage()?.getItem(THEME_KEY)
    return isTheme(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

/** Puts `theme` on the page. The inline script in index.html does the same before
 * first paint, where this module has not loaded yet (src/lib/theme.test.ts compares them). */
export function applyTheme(theme: Theme): void {
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia(DARK_SYSTEM).matches)
  document.documentElement.classList.toggle('dark', dark)
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', dark ? THEME_COLORS.dark : THEME_COLORS.light)
}

let current = readStoredTheme()
const listeners = new Set<() => void>()

function update(theme: Theme): void {
  current = theme
  applyTheme(theme)
  for (const listener of listeners) listener()
}

export function currentTheme(): Theme {
  return current
}

/** Takes effect even where it cannot be remembered. */
export function chooseTheme(theme: Theme): void {
  try {
    browserStorage()?.setItem(THEME_KEY, theme)
  } catch {
    // Blocked or full storage: this page keeps the choice until it is closed.
  }
  update(theme)
}

/** Keeps the page in step with the system and with choices made in other tabs. */
export function followTheme(): () => void {
  const media = window.matchMedia(DARK_SYSTEM)
  const onSystem = () => {
    applyTheme(current)
  }
  const onStorage = (event: StorageEvent) => {
    // `key` is null when the whole storage was cleared.
    if (event.key === THEME_KEY || event.key === null) update(readStoredTheme())
  }
  media.addEventListener('change', onSystem)
  window.addEventListener('storage', onStorage)
  return () => {
    media.removeEventListener('change', onSystem)
    window.removeEventListener('storage', onStorage)
  }
}

/** The current choice, for controls that show or change it. */
export function useTheme(): Theme {
  return useSyncExternalStore((onChange) => {
    listeners.add(onChange)
    return () => {
      listeners.delete(onChange)
    }
  }, currentTheme)
}
