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

    // Shown once the session's retries have failed.
    expect(await screen.findByText(firstTitle, {}, { timeout: 8000 })).toBeInTheDocument()
  }, 10_000)

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

const BANNER = "You're offline. Today's digest is the saved copy; other pages need a connection."

describe('offline, the app says so', () => {
  it('shows no banner online', async () => {
    fakeApi({ 'GET /api/v1/auth/session': () => json(loggedIn) })
    renderApp()

    expect(await screen.findByText(firstTitle)).toBeInTheDocument()
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
  })

  it('shows the banner and when today’s copy was saved', async () => {
    await readTodayOnline()
    onlineManager.setOnline(false)
    fakeApi({})

    renderApp('/', { persister: createPersister(localStorage) })

    expect(await screen.findByRole('status')).toHaveTextContent(BANNER)
    expect(screen.getByText(/^Saved at /)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Sign in again' })).not.toBeInTheDocument()
  })

  it('tells when the copy was saved if the server is out of reach', async () => {
    await readTodayOnline()
    fakeApi({
      'GET /api/v1/auth/session': () => Response.error(),
      'GET /api/v1/digests/today': () => Response.error(),
    })

    renderApp('/', { persister: createPersister(localStorage) })

    expect(await screen.findByText(/^Saved at /, {}, { timeout: 8000 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in again' })).toBeInTheDocument()
  }, 10_000)

  it('says a page without a saved copy needs a connection', async () => {
    await readTodayOnline()
    onlineManager.setOnline(false)
    fakeApi({})

    renderApp('/archive', { persister: createPersister(localStorage) })

    expect(await screen.findByText('This page needs a connection.')).toBeInTheDocument()
  })
})

describe('the saved copy and who reads it', () => {
  it('is forgotten by logging out offline', async () => {
    await readTodayOnline()
    onlineManager.setOnline(false)
    fakeApi({})
    const user = userEvent.setup()
    renderApp('/', { persister: createPersister(localStorage) })

    await user.click(await screen.findByRole('button', { name: 'Log out' }))

    await waitFor(() => {
      expect(saved()).not.toContain(firstTitle)
    })
    expect(screen.queryByText(firstTitle)).not.toBeInTheDocument()
  })

  it('is not shown online before the server confirms the session', async () => {
    await readTodayOnline()
    let answer: () => void = () => undefined
    const answered = new Promise<void>((resolve) => {
      answer = resolve
    })
    fakeApi({
      'GET /api/v1/auth/session': async () => {
        await answered
        return json(loggedOut)
      },
    })

    renderApp('/', { persister: createPersister(localStorage) })

    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(screen.queryByText(firstTitle)).not.toBeInTheDocument()
    answer()
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  })

  it('is forgotten when the proxy names another reader', async () => {
    const alice: SessionOut = {
      mode: 'header',
      authenticated: true,
      user: 'alice',
      csrf_token: 'a',
    }
    fakeApi({ 'GET /api/v1/auth/session': () => json(alice) })
    const first = renderApp('/', { persister: createPersister(localStorage) })
    expect(await screen.findByText(firstTitle)).toBeInTheDocument()
    await waitFor(() => {
      expect(saved()).toContain(firstTitle)
    })
    first.unmount()

    let answer: () => void = () => undefined
    const answered = new Promise<void>((resolve) => {
      answer = resolve
    })
    fakeApi({
      'GET /api/v1/auth/session': () => json({ ...alice, user: 'bob', csrf_token: 'b' }),
      'GET /api/v1/digests/today': async () => {
        await answered
        return json({ date: digest.date, articles: [] })
      },
    })
    renderApp('/', { persister: createPersister(localStorage) })

    // Bob is in, and alice's digest is not shown while his own loads.
    expect(await screen.findByRole('link', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.queryByText(firstTitle)).not.toBeInTheDocument()
    answer()
    expect(await screen.findByText('No digest yet today.')).toBeInTheDocument()
    await waitFor(() => {
      expect(saved()).not.toContain(firstTitle)
    })
  })

  it('offers to sign in again when the server answers with something else', async () => {
    fakeApi({ 'GET /api/v1/auth/session': () => Response.error() })

    renderApp('/')

    const link = await screen.findByRole('link', { name: 'Sign in again' }, { timeout: 8000 })
    expect(link).toHaveAttribute('href', '/?signin')
  }, 10_000)
})
