const QUERY = '(prefers-color-scheme: dark)'

let systemDark = false
const listeners = new Set<() => void>()

/** What the operating system asks for; listeners hear the change as in a browser. */
export function setSystemDark(dark: boolean): void {
  systemDark = dark
  for (const listener of [...listeners]) listener()
}

export function resetSystemTheme(): void {
  systemDark = false
  listeners.clear()
}

/** jsdom has no `matchMedia`; this one knows the only query the app asks. */
export function installMatchMedia(): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      media: query,
      get matches() {
        return query === QUERY && systemDark
      },
      addEventListener: (_type: 'change', listener: () => void) => {
        listeners.add(listener)
      },
      removeEventListener: (_type: 'change', listener: () => void) => {
        listeners.delete(listener)
      },
    }),
  })
}
