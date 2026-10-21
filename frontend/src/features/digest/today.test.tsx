import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { digest, ranking } from '@/demo/data'
import { json } from '@/test/fake-api'
import { nth } from '@/test/nth'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('today', () => {
  it('shows the digest as cards, in order', async () => {
    loggedInApi({ 'GET /api/v1/digests/today': () => json(digest) })
    renderApp('/')

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(3)
    const first = within(nth(items, 0))
    expect(first.getByRole('link', { name: /PostgreSQL 19 beta/ })).toHaveAttribute(
      'href',
      '/open?id=1&sig=demo',
    )
    expect(first.getByText('Opened')).toBeInTheDocument()
    expect(within(nth(items, 1)).queryByText('Opened')).not.toBeInTheDocument()
  })

  it('marks an article opened as soon as it is followed', async () => {
    loggedInApi({ 'GET /api/v1/digests/today': () => json(digest) })
    const user = userEvent.setup()
    renderApp('/')

    const link = await screen.findByRole('link', { name: /Linus Torvalds/ })
    link.addEventListener('click', (event) => {
      event.preventDefault() // jsdom cannot open tabs
    })
    await user.click(link)

    const card = link.closest('[data-slot="card"]')
    if (!(card instanceof HTMLElement)) throw new Error('the link is not in a card')
    expect(within(card).getByText('Opened')).toBeInTheDocument()
  })

  it('explains why an article is where it is', async () => {
    const api = loggedInApi({
      'GET /api/v1/digests/today': () => json(digest),
      'GET /api/v1/articles/:id/ranking': () => json(ranking),
    })
    const user = userEvent.setup()
    renderApp('/')

    const buttons = await screen.findAllByRole('button', { name: 'Why here?' })
    await user.click(nth(buttons, 1))

    const breakdown = await screen.findByRole('region', { name: 'How it got here' })
    expect(within(breakdown).getByText('The day started with 200 articles')).toBeInTheDocument()
    expect(within(breakdown).getByText('Ranked 4 of 40 candidates')).toBeInTheDocument()
    expect(within(breakdown).getByText('Ranking: llm; duplicates: judge')).toBeInTheDocument()
    expect(api.sent('GET /api/v1/articles/:id/ranking')[0]?.url).toContain('/articles/2/')
  })
})
