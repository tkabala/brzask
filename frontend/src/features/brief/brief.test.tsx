import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { BriefOut } from '@/client/types.gen'
import { articles, briefs } from '@/demo/data'
import { problem } from '@/test/fake-api'
import { nth } from '@/test/nth'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

function briefFrom(basis: BriefOut['basis']): BriefOut {
  const brief = briefs.find((b) => b.basis === basis)
  if (!brief) throw new Error(`no demo brief from ${basis}`)
  return brief
}

const text = briefFrom('full_text')
const video = briefFrom('transcript')
const unbriefed = nth(articles, 1)

/** Matches an accessible name that contains `title`. */
const titled = (title: string) => (name: string) => name.includes(title)

describe('brief page', () => {
  it('renders gist, points, caveats and the basis line', async () => {
    loggedInApi({})
    renderApp(`/articles/${String(text.article.id)}`)

    expect(
      await screen.findByRole('heading', { level: 1, name: text.article.title }),
    ).toBeInTheDocument()
    expect(screen.getByText(text.gist)).toBeInTheDocument()
    for (const point of text.points) expect(screen.getByText(point)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Caveats' })).toBeInTheDocument()
    for (const caveat of text.caveats) expect(screen.getByText(caveat)).toBeInTheDocument()
    expect(screen.getByText('From the full text')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Chapters' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open original' })).toHaveAttribute(
      'href',
      text.article.open_url,
    )
  })

  it('lists chapters as links through open_url', async () => {
    loggedInApi({})
    renderApp(`/articles/${String(video.article.id)}`)

    const heading = await screen.findByRole('heading', { name: 'Chapters' })
    const list = heading.nextElementSibling
    if (!(list instanceof HTMLElement)) throw new Error('no list after the chapters heading')
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(video.chapters.length)
    video.chapters.forEach((chapter, i) => {
      expect(
        within(nth(items, i)).getByRole('link', { name: titled(chapter.title) }),
      ).toHaveAttribute('href', chapter.open_url)
    })
    expect(within(nth(items, 1)).getByText('1:35')).toBeInTheDocument()
    expect(within(nth(items, 2)).getByText('12:34')).toBeInTheDocument()
    expect(within(nth(items, 3)).getByText('1:02:05')).toBeInTheDocument()
    expect(screen.getByText('From the transcript')).toBeInTheDocument()
  })

  it('records the view once', async () => {
    const api = loggedInApi({})
    renderApp(`/articles/${String(text.article.id)}`)

    await screen.findByText(text.gist)
    await vi.waitFor(() => {
      expect(api.sent('POST /api/v1/articles/:id/brief-open')).toHaveLength(1)
    })
    // The answer updates the cached brief, which renders the page again.
    await new Promise((resolve) => setTimeout(resolve, 50))
    const posts = api.sent('POST /api/v1/articles/:id/brief-open')
    expect(posts).toHaveLength(1)
    expect(nth(posts, 0).url).toContain(`/articles/${String(text.article.id)}/brief-open`)
    expect(nth(posts, 0).headers.get('X-CSRF-Token')).toBe('csrf-1')
  })

  it('offers the original when the brief is missing', async () => {
    loggedInApi({
      'GET /api/v1/articles/:id/brief': () => problem(404, 'Not Found', 'no brief'),
    })
    renderApp(`/articles/${String(unbriefed.id)}`)

    expect(await screen.findByText('This article has no brief.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Open original' })).toHaveAttribute(
      'href',
      unbriefed.open_url,
    )
    expect(screen.getByRole('heading', { level: 1, name: unbriefed.title })).toBeInTheDocument()
  })

  it('says the brief is missing when the article is gone too', async () => {
    loggedInApi({})
    renderApp('/articles/999999')

    expect(await screen.findByText('This article has no brief.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open original' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back/ })).toBeInTheDocument()
  })

  it('shows other errors as a problem with a retry', async () => {
    // A 4xx, which is not retried, so the problem shows at once.
    loggedInApi({
      'GET /api/v1/articles/:id/brief': () => problem(403, 'Forbidden', 'Not for this reader.'),
    })
    renderApp(`/articles/${String(text.article.id)}`)

    expect(await screen.findByText('Not for this reader.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('open original marks the article opened', async () => {
    // No brief view recorded, so only following the original marks the card.
    loggedInApi({
      'POST /api/v1/articles/:id/brief-open': () => problem(404, 'Not Found', 'no brief'),
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('link', { name: titled(text.article.title) }))
    const original = await screen.findByRole('link', { name: 'Open original' })
    original.addEventListener('click', (event) => {
      event.preventDefault() // jsdom cannot open tabs
    })
    await user.click(original)
    await user.click(screen.getByRole('link', { name: /Back/ }))

    const card = (await screen.findByRole('link', { name: titled(text.article.title) })).closest(
      '[data-slot="card"]',
    )
    if (!(card instanceof HTMLElement)) throw new Error('the link is not in a card')
    expect(within(card).getByText('Opened')).toBeInTheDocument()
  })

  it('marks the card opened after reading the brief', async () => {
    loggedInApi({})
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('link', { name: titled(text.article.title) }))
    await screen.findByText(text.gist)
    await user.click(screen.getByRole('link', { name: /Back/ }))

    const card = (await screen.findByRole('link', { name: titled(text.article.title) })).closest(
      '[data-slot="card"]',
    )
    if (!(card instanceof HTMLElement)) throw new Error('the link is not in a card')
    expect(await within(card).findByText('Opened')).toBeInTheDocument()
  })
})
