import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom does not implement scrolling; the router restores scroll on navigation.
vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)

afterEach(() => {
  cleanup()
})
