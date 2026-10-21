import { setupServer } from 'msw/node'

import { handlers } from '@/demo/handlers'

/** The demo API for tests; each test may add overrides with `server.use()`. */
export const server = setupServer(...handlers)
