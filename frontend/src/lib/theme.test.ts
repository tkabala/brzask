import index from '../../index.html?raw'

import { setSystemDark } from '@/test/color-scheme'

import {
  applyTheme,
  chooseTheme,
  currentTheme,
  followTheme,
  readStoredTheme,
  THEME_COLORS,
  THEME_KEY,
} from './theme'

function themeColor(): string | null | undefined {
  return document.querySelector('meta[name="theme-color"]')?.getAttribute('content')
}

function isDark(): boolean {
  return document.documentElement.classList.contains('dark')
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="theme-color" content="#123456" />'
})

afterEach(() => {
  vi.restoreAllMocks()
  chooseTheme('system')
  localStorage.clear()
  document.documentElement.className = ''
  document.head.innerHTML = ''
})

describe('readStoredTheme', () => {
  it('is what was chosen', () => {
    localStorage.setItem(THEME_KEY, 'dark')
    expect(readStoredTheme()).toBe('dark')
  })

  it('is the system without a choice', () => {
    expect(readStoredTheme()).toBe('system')
  })

  it('is the system for a value it does not know', () => {
    localStorage.setItem(THEME_KEY, 'sepia')
    expect(readStoredTheme()).toBe('system')
  })

  it('is the system where storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(readStoredTheme()).toBe('system')
  })
})

describe('applyTheme', () => {
  it.each([
    ['light', false, false],
    ['light', true, false],
    ['dark', false, true],
    ['dark', true, true],
    ['system', false, false],
    ['system', true, true],
  ] as const)('%s with a dark system %s: dark is %s', (theme, system, dark) => {
    setSystemDark(system)
    applyTheme(theme)
    expect(isDark()).toBe(dark)
    expect(themeColor()).toBe(dark ? THEME_COLORS.dark : THEME_COLORS.light)
  })

  it('works on a page without the meta tag', () => {
    document.head.innerHTML = ''
    applyTheme('dark')
    expect(isDark()).toBe(true)
  })
})

describe('chooseTheme', () => {
  it('stores the choice and applies it', () => {
    chooseTheme('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(currentTheme()).toBe('dark')
    expect(isDark()).toBe(true)
  })

  it('still applies where storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    chooseTheme('dark')
    expect(currentTheme()).toBe('dark')
    expect(isDark()).toBe(true)
  })
})

describe('followTheme', () => {
  it('follows the system while the choice is system', () => {
    const stop = followTheme()
    setSystemDark(true)
    expect(isDark()).toBe(true)
    setSystemDark(false)
    expect(isDark()).toBe(false)
    stop()
  })

  it('ignores the system once a theme is chosen', () => {
    const stop = followTheme()
    chooseTheme('light')
    setSystemDark(true)
    expect(isDark()).toBe(false)
    stop()
  })

  it('takes a choice made in another tab', () => {
    const stop = followTheme()
    localStorage.setItem(THEME_KEY, 'dark')
    window.dispatchEvent(new StorageEvent('storage', { key: THEME_KEY, newValue: 'dark' }))
    expect(currentTheme()).toBe('dark')
    expect(isDark()).toBe(true)
    stop()
  })

  it('takes storage being cleared in another tab', () => {
    chooseTheme('dark')
    const stop = followTheme()
    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: null }))
    expect(currentTheme()).toBe('system')
    expect(isDark()).toBe(false)
    stop()
  })

  it('ignores other keys', () => {
    chooseTheme('dark')
    const stop = followTheme()
    localStorage.removeItem(THEME_KEY)
    window.dispatchEvent(new StorageEvent('storage', { key: 'i18nextLng' }))
    expect(currentTheme()).toBe('dark')
    stop()
  })
})

describe('the inline script in index.html', () => {
  const code = /<script>([\s\S]*?)<\/script>/.exec(index)?.[1]

  function run(): void {
    if (code === undefined) throw new Error('index.html has no inline script')
    // Indirect eval: the script runs as the browser runs it, in global scope.
    ;(0, eval)(code)
  }

  it('comes before anything else that loads', () => {
    const head = index.slice(index.indexOf('<head>'), index.indexOf('</head>'))
    const script = head.indexOf('<script>')
    expect(script).toBeGreaterThan(-1)
    expect(head.indexOf('<meta name="theme-color"')).toBeLessThan(script)
    expect(head.indexOf('<link')).toBeGreaterThan(script)
  })

  it.each([
    [null, false],
    [null, true],
    ['system', false],
    ['system', true],
    ['light', false],
    ['light', true],
    ['dark', false],
    ['dark', true],
    ['sepia', false],
    ['sepia', true],
  ])('with %s stored and a dark system %s it agrees with the app', (stored, system) => {
    if (stored !== null) localStorage.setItem(THEME_KEY, stored)
    setSystemDark(system)

    run()
    const fromScript = [isDark(), themeColor()]

    document.documentElement.className = ''
    applyTheme(readStoredTheme())
    expect(fromScript).toEqual([isDark(), themeColor()])
  })

  it('follows the system where storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    setSystemDark(true)
    run()
    expect(isDark()).toBe(true)
    expect(themeColor()).toBe(THEME_COLORS.dark)
  })
})
