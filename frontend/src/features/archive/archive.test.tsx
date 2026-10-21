import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { days, digest } from '@/demo/data'
import { json } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('archive', () => {
  it('pages through days and opens one', async () => {
    const api = loggedInApi({
      'GET /api/v1/digests': (request) =>
        new URL(request.url).searchParams.get('cursor') === 'page2'
          ? json({ items: days.slice(2), next_cursor: null })
          : json({ items: days.slice(0, 2), next_cursor: 'page2' }),
      'GET /api/v1/digests/:day': () => json({ ...digest, date: '2026-10-19' }),
    })
    const user = userEvent.setup()
    renderApp('/archive')

    expect(await screen.findByRole('link', { name: 'Wednesday, October 21, 2026' })).toBeVisible()
    expect(screen.getByText('7 articles · 1 opened')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Load more' }))
    const third = await screen.findByRole('link', { name: 'Monday, October 19, 2026' })
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()

    await user.click(third)

    expect(
      await screen.findByRole('heading', { name: 'Digest of Monday, October 19, 2026' }),
    ).toBeInTheDocument()
    expect(api.sent('GET /api/v1/digests/:day')[0]?.url).toMatch(/\/digests\/2026-10-19$/)
  })

  it('says when a day had no digest', async () => {
    loggedInApi({ 'GET /api/v1/digests/:day': () => json({ date: '2026-10-18', articles: [] }) })
    renderApp('/archive/2026-10-18')

    expect(await screen.findByText('No digest that day.')).toBeInTheDocument()
  })
})
