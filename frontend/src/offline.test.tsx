import { onlineManager } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { SessionOut } from '@/client/types.gen'
import { digest } from '@/demo/data'
import { initI18n } from '@/i18n'
import { CACHE_KEY, createPersister } from '@/lib/offline-cache'
import { fakeApi, json, loggedIn, loggedOut, problem } from '@/test/fake-api'
import { renderApp } from '@/test/render'

const firstTitle = digest.articles[0]?.title ?? ''

function saved(): string {
  return localStorage.getItem(CACHE_KEY) ?? ''
}

async function readTodayOnline(): Promise<void> {
  fakeApi({ 'GET /api/v1/auth/session': () => json(loggedIn) })
  const view = renderApp('/', { persister: createPersister(localStorage) })
  expect(await screen.findByText(firstTitle)).toBeInTheDocument()
  await waitFor(() => {
    expect(saved()).toContain(firstTitle)
  })
  view.unmount()
}

beforeEach(() => {
  initI18n('en')
  localStorage.clear()
})

afterEach(() => {
  onlineManager.setOnline(true)
})

describe('saved for offline', () => {
  it('saves today’s digest as it is read', async () => {
    await readTodayOnline()
  })

  it('shows the saved digest when the app starts offline', async () => {
    await readTodayOnline()
    onlineManager.setOnline(false)
    const api = fakeApi({})

    renderApp('/', { persister: createPersister(localStorage) })

    expect(await screen.findByText(firstTitle)).toBeInTheDocument()
    expect(api.requests).toHaveLength(0)
  })

  it('shows the saved digest when the server cannot be reached', async () => {
    await readTodayOnline()
    fakeApi({
      'GET /api/v1/auth/session': () => Response.error(),
      'GET /api/v1/digests/today': () => Response.error(),
    })

    renderApp('/', { persister: createPersister(localStorage) })

    expect(await screen.findByText(firstTitle)).toBeInTheDocument()
  })

  it('forgets it on logout', async () => {
    await readTodayOnline()
    let session: SessionOut = loggedIn
    fakeApi({
      'GET /api/v1/auth/session': () => json(session),
      'POST /api/v1/auth/logout': () => {
        session = loggedOut
        return new Response(null, { status: 204 })
      },
    })
    const user = userEvent.setup()
    renderApp('/', { persister: createPersister(localStorage) })

    await user.click(await screen.findByRole('button', { name: 'Log out' }))

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(saved()).not.toContain(firstTitle)
  })

  it('forgets it when the API answers 401', async () => {
    await readTodayOnline()
    fakeApi({
      'GET /api/v1/auth/session': () => json(loggedIn),
      'GET /api/v1/digests/today': () => problem(401, 'Unauthorized', 'Log in first.'),
    })

    renderApp('/', { persister: createPersister(localStorage) })

    await waitFor(() => {
      expect(saved()).not.toContain(firstTitle)
    })
  })

  it('forgets it when the server no longer knows the reader', async () => {
    await readTodayOnline()
    fakeApi({ 'GET /api/v1/auth/session': () => json(loggedOut) })

    renderApp('/', { persister: createPersister(localStorage) })

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    await waitFor(() => {
      expect(saved()).not.toContain(firstTitle)
    })
  })
})
