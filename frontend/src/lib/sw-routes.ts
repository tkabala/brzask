/**
 * Navigations the service worker leaves to the server, matched against the
 * path and query string. The API's own paths, so an article link opened
 * offline fails as a page instead of opening the app; and any address with
 * `?signin`, so a proxy in front of brzask sees the visit and can ask for
 * its login again.
 *
 * The service worker is built once for every path prefix (BASE_URL), so the
 * server's paths match after any prefix. An app route with a path segment
 * named like one of them would bypass the service worker too; there is none.
 */
export const NOT_THE_APP: RegExp[] = [
  /^[^?]*\/(api|open|feed|healthz|readyz)([/?]|$)/,
  /[?&]signin(&|$)/,
]
