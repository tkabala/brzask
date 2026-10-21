import { initI18n } from '@/i18n'
import { fakeApi, json, loggedIn } from '@/test/fake-api'

type Handlers = Parameters<typeof fakeApi>[0]

/** English, logged in, and the given handlers. */
export function loggedInApi(handlers: Handlers) {
  initI18n('en')
  return fakeApi({ 'GET /api/v1/auth/session': () => json(loggedIn), ...handlers })
}
