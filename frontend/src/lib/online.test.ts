import { onlineManager } from '@tanstack/react-query'

import { followBrowserOnline } from './online'

afterEach(() => {
  vi.restoreAllMocks()
  onlineManager.setOnline(true)
})

it('starts offline when the browser already is', () => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)

  followBrowserOnline()

  expect(onlineManager.isOnline()).toBe(false)
})
