import { createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'

import { App } from '@/app'
import { configureApi } from '@/lib/api'
import { createQueryClient } from '@/lib/query'

/** The whole app at `path`, against whatever `fakeApi` serves. */
export function renderApp(path = '/') {
  configureApi('http://localhost')
  return render(
    <App
      queryClient={createQueryClient()}
      history={createMemoryHistory({ initialEntries: [path] })}
    />,
  )
}
