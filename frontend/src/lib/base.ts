/**
 * Where the app is served: `/`, or a prefix such as `/brzask/` behind a
 * reverse proxy. The server names it in the `<base>` element of index.html
 * (BASE_URL); without one (dev server, tests, Storybook) it is the root.
 */
export function appBase(): string {
  if (document.querySelector('base[href]') === null) return '/'
  return new URL(document.baseURI).pathname
}

/** The generated client's base URL; its paths start with `/api/v1`. */
export function apiBaseUrl(): string {
  return window.location.origin + appBase().replace(/\/$/, '')
}

/** TanStack Router's basepath: the prefix without its trailing slash. */
export function routerBasepath(): string {
  return appBase().replace(/(.)\/$/, '$1')
}

/** The address that skips the saved app: `?signin` is never answered by the
 * service worker, so a proxy in front of brzask sees the visit and can ask
 * for its login again (`src/lib/sw-routes.ts`). */
export function signInUrl(): string {
  return `${appBase()}?signin`
}
