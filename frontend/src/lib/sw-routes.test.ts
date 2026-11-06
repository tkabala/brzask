import { NOT_THE_APP } from './sw-routes'

const servedByApi = (url: string) => NOT_THE_APP.some((pattern) => pattern.test(url))

it.each([
  '/api/v1/digests/today',
  '/open?id=1&sig=x',
  '/feed?token=t',
  '/healthz',
  '/readyz',
  '/?signin',
  '/archive?signin',
  '/brzask/api/v1/digests/today',
  '/brzask/open?id=1&sig=x',
  '/brzask/feed?token=t',
  '/brzask/readyz',
  '/brzask/?signin',
])('%s goes to the server', (url) => {
  expect(servedByApi(url)).toBe(true)
})

it.each([
  '/',
  '/archive/2026-10-01',
  '/openings',
  '/search?q=signing',
  '/?q=signin2',
  '/brzask/',
  '/brzask/archive/2026-10-01',
  '/brzask/sources?q=api',
  '/brzask/search?q=open',
])('%s is the app', (url) => {
  expect(servedByApi(url)).toBe(false)
})
