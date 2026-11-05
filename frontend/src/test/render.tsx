import { createMemoryHistory } from '@tanstack/react-router'
import type { Persister } from '@tanstack/react-query-persist-client'
import { render } from '@testing-library/react'

import { App } from '@/app'
import { configureApi } from '@/lib/api'
import { createQueryClient } from '@/lib/query'

/** The whole app at `path`, against whatever `fakeApi` serves; with a
 * persister it keeps its offline copy as the real app does. */
export function renderApp(path = '/', { persister }: { persister?: Persister } = {}) {
  configureApi('http://localhost')
  return render(
    <App
      queryClient={createQueryClient()}
      history={createMemoryHistory({ initialEntries: [path] })}
      {...(persister ? { persister } : {})}
    />,
  )
}
