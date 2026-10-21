import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from '@/app'
import type { DigestOut, SessionOut } from '@/client/types.gen'
import { initI18n } from '@/i18n'
import { configureApi } from '@/lib/api'
import { createQueryClient } from '@/lib/query'
import { emptyDigest, fakeApi, json, loggedIn, loggedOut, problem } from '@/test/fake-api'

function renderApp() {
  configureApi('http://localhost')
  return render(
    <App
      queryClient={createQueryClient()}
      history={createMemoryHistory({ initialEntries: ['/'] })}
    />,
  )
}

beforeEach(() => {
  initI18n('en')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('logging in', () => {
  it('shows the login, refuses a wrong password, then shows the empty digest', async () => {
    let session: SessionOut = loggedOut
    const api = fakeApi({
      'GET /api/v1/auth/session': () => json(session),
      'POST /api/v1/auth/login': async (request) => {
        const { password } = (await request.json()) as { password: string }
        if (password !== 'right') return problem(401, 'Unauthorized', 'Wrong password.')
        session = loggedIn
        return json(loggedIn)
      },
      'GET /api/v1/digests/today': () => json(emptyDigest),
    })
    const user = userEvent.setup()
    renderApp()

    await user.type(await screen.findByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('Wrong password.')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveValue('')

    await user.type(screen.getByLabelText('Password'), 'right')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
    expect(await screen.findByText('No digest yet today.')).toBeInTheDocument()
    expect(api.requests.some((r) => r.url.endsWith('/api/v1/digests/today'))).toBe(true)
  })

  it('asks for the password before sending anything', async () => {
    const api = fakeApi({ 'GET /api/v1/auth/session': () => json(loggedOut) })
    const user = userEvent.setup()
    renderApp()

    await user.click(await screen.findByRole('button', { name: 'Log in' }))

    expect(await screen.findByText('Enter the password.')).toBeInTheDocument()
    expect(api.requests.filter((r) => r.method === 'POST')).toHaveLength(0)
  })

  it('tells how long a lockout lasts', async () => {
    fakeApi({
      'GET /api/v1/auth/session': () => json(loggedOut),
      'POST /api/v1/auth/login': () =>
        problem(429, 'Too Many Requests', 'Too many wrong passwords.', { 'Retry-After': '900' }),
    })
    const user = userEvent.setup()
    renderApp()

    await user.type(await screen.findByLabelText('Password'), 'x')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByText(/Try again in 15 min/)).toBeInTheDocument()
  })

  it('points to the proxy when it authenticates', async () => {
    fakeApi({
      'GET /api/v1/auth/session': () => json({ ...loggedOut, mode: 'header' }),
    })
    renderApp()

    expect(
      await screen.findByRole('heading', { name: 'Sign in through your proxy' }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })
})

describe('logged in', () => {
  it('lists today’s articles through their open links', async () => {
    const digest: DigestOut = {
      date: '2026-10-21',
      articles: [
        {
          id: 7,
          link: 'https://news.example/a',
          open_url: '/open?id=7&sig=abc',
          title: 'Postgres 18 is out',
          original_title: 'Postgres 18 is out',
          summary: 'What changed.',
          why_it_matters: null,
          topic: 'Postgres',
          source: { id: 1, name: 'PG News' },
          state: 'shown',
          published_at: null,
          first_seen_at: '2026-10-21T06:00:00Z',
          digest_date: '2026-10-21',
          position: 1,
          shown_at: '2026-10-21T07:00:00Z',
          opened_at: null,
        },
      ],
    }
    fakeApi({
      'GET /api/v1/auth/session': () => json(loggedIn),
      'GET /api/v1/digests/today': () => json(digest),
    })
    renderApp()

    const link = await screen.findByRole('link', { name: 'Postgres 18 is out' })
    expect(link).toHaveAttribute('href', '/open?id=7&sig=abc')
  })

  it('shows a problem from the API with a retry', async () => {
    let fail = true
    fakeApi({
      'GET /api/v1/auth/session': () => json(loggedIn),
      'GET /api/v1/digests/today': () =>
        fail
          ? problem(503, 'Service Unavailable', 'The database is unreachable.')
          : json(emptyDigest),
    })
    const user = userEvent.setup()
    renderApp()

    expect(
      await screen.findByText('The database is unreachable.', {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No digest yet today.')).toBeInTheDocument()
  })

  it('goes back to the login when the session ends', async () => {
    let session: SessionOut = loggedIn
    fakeApi({
      'GET /api/v1/auth/session': () => json(session),
      'GET /api/v1/digests/today': () => {
        session = loggedOut
        return problem(401, 'Unauthorized', 'Log in first.')
      },
    })
    renderApp()

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  })

  it('logs out with the CSRF token', async () => {
    let session: SessionOut = loggedIn
    const api = fakeApi({
      'GET /api/v1/auth/session': () => json(session),
      'GET /api/v1/digests/today': () => json(emptyDigest),
      'POST /api/v1/auth/logout': () => {
        session = loggedOut
        return new Response(null, { status: 204 })
      },
    })
    const user = userEvent.setup()
    renderApp()

    await user.click(await screen.findByRole('button', { name: 'Log out' }))

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    const logout = api.requests.find((r) => r.url.endsWith('/auth/logout'))
    expect(logout?.headers.get('X-CSRF-Token')).toBe('csrf-1')
    // Reads carry no token.
    const read = api.requests.find((r) => r.url.endsWith('/digests/today'))
    expect(read?.headers.get('X-CSRF-Token')).toBeNull()
  })

  it('speaks Polish', async () => {
    fakeApi({
      'GET /api/v1/auth/session': () => json(loggedIn),
      'GET /api/v1/digests/today': () => json(emptyDigest),
    })
    initI18n('pl')
    const user = userEvent.setup()
    renderApp()

    expect(await screen.findByRole('heading', { name: 'Dziś' })).toBeInTheDocument()
    await waitFor(() => {
      expect(document.documentElement.lang).toBe('pl')
    })
    await user.selectOptions(screen.getByLabelText('Język'), 'en')
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
  })
})
