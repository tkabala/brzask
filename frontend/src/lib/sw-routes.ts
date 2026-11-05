/**
 * Navigations the service worker leaves to the server, matched against the
 * path and query string. The API's own paths, so an article link opened
 * offline fails as a page instead of opening the app; and any address with
 * `?signin`, so a proxy in front of brzask sees the visit and can ask for
 * its login again.
 */
export const NOT_THE_APP: RegExp[] = [
  /^\/(api|open|feed|healthz|readyz)([/?]|$)/,
  /[?&]signin(&|$)/,
]
