import { apiBaseUrl, appBase, routerBasepath, signInUrl } from './base'

afterEach(() => {
  document.querySelectorAll('base').forEach((element) => {
    element.remove()
  })
})

function serveAt(href: string): void {
  const base = document.createElement('base')
  base.href = href
  document.head.prepend(base)
}

it('is the root without a base element (dev server, tests, Storybook)', () => {
  expect(appBase()).toBe('/')
  expect(apiBaseUrl()).toBe(window.location.origin)
  expect(routerBasepath()).toBe('/')
  expect(signInUrl()).toBe('/?signin')
})

it('is the root with the base element the server sends at the root', () => {
  serveAt('/')

  expect(appBase()).toBe('/')
  expect(apiBaseUrl()).toBe(window.location.origin)
  expect(routerBasepath()).toBe('/')
})

it('follows the base element under a prefix', () => {
  serveAt('/brzask/')

  expect(appBase()).toBe('/brzask/')
  expect(apiBaseUrl()).toBe(`${window.location.origin}/brzask`)
  expect(routerBasepath()).toBe('/brzask')
  expect(signInUrl()).toBe('/brzask/?signin')
})
