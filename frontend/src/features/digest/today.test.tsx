import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { ArticleOut } from '@/client/types.gen'
import { articles, digest, ranking } from '@/demo/data'
import { json } from '@/test/fake-api'
import { nth } from '@/test/nth'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

const [first, second, third, fourth] = [0, 1, 2, 3].map((i) => nth(articles, i)) as [
  ArticleOut,
  ArticleOut,
  ArticleOut,
  ArticleOut,
]

/** Matches an accessible name that contains `title`. */
const titled = (title: string) => (name: string) => name.includes(title)

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('today', () => {
  it('shows the digest as cards, in order', async () => {
    loggedInApi({ 'GET /api/v1/digests/today': () => json(digest) })
    renderApp('/')

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(digest.articles.length)
    expect(within(nth(items, 0)).getByRole('link', { name: titled(first.title) })).toHaveAttribute(
      'href',
      `/open?id=${String(first.id)}&sig=demo`,
    )
    expect(third.opened_at).not.toBeNull()
    expect(within(nth(items, 2)).getByText('Opened')).toBeInTheDocument()
    expect(within(nth(items, 0)).queryByText('Opened')).not.toBeInTheDocument()
  })

  it('marks an article opened as soon as it is followed', async () => {
    loggedInApi({ 'GET /api/v1/digests/today': () => json(digest) })
    const user = userEvent.setup()
    renderApp('/')

    const link = await screen.findByRole('link', { name: titled(second.title) })
    link.addEventListener('click', (event) => {
      event.preventDefault() // jsdom cannot open tabs
    })
    await user.click(link)

    const card = link.closest('[data-slot="card"]')
    if (!(card instanceof HTMLElement)) throw new Error('the link is not in a card')
    expect(within(card).getByText('Opened')).toBeInTheDocument()
  })

  it('marks an article opened on a middle click, not on a right click', async () => {
    loggedInApi({ 'GET /api/v1/digests/today': () => json(digest) })
    renderApp('/')

    const card = async (title: string) => {
      const link = await screen.findByRole('link', { name: titled(title) })
      const found = link.closest('[data-slot="card"]')
      if (!(found instanceof HTMLElement)) throw new Error('the link is not in a card')
      return { link, card: within(found) }
    }
    const menu = await card(second.title)
    const tab = await card(fourth.title)
    expect(tab.card.queryByText('Opened')).not.toBeInTheDocument()

    fireEvent(menu.link, new MouseEvent('auxclick', { bubbles: true, button: 2 }))
    fireEvent(tab.link, new MouseEvent('auxclick', { bubbles: true, button: 1 }))

    expect(await tab.card.findByText('Opened')).toBeInTheDocument()
    expect(menu.card.queryByText('Opened')).not.toBeInTheDocument()
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
    expect(ranking.article_id).toBe(second.id)
    expect(
      within(breakdown).getByText(`The day started with ${String(ranking.pool)} articles`),
    ).toBeInTheDocument()
    expect(within(breakdown).getByText('Ranked 3 of 40 candidates')).toBeInTheDocument()
    expect(within(breakdown).getByText('Ranking: llm; duplicates: judge')).toBeInTheDocument()
    expect(api.sent('GET /api/v1/articles/:id/ranking')[0]?.url).toContain(
      `/articles/${String(second.id)}/`,
    )
  })
})
