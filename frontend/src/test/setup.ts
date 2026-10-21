import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { resetDemo } from '@/demo/handlers'

import { server } from './server'

// jsdom does not implement scrolling; the router restores scroll on navigation.
vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)

// A request no handler answers is a mistake in the test, not a network call.
beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetDemo()
})

afterAll(() => {
  server.close()
})
