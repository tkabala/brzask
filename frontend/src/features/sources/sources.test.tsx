import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { SourceOut } from '@/client/types.gen'
import { pendingSources, sources } from '@/demo/data'
import { json, problem } from '@/test/fake-api'
import { nth } from '@/test/nth'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

const planner = nth(pendingSources, 0)
const busiest = nth(
  sources.filter((source) => source.name === 'Incident Review'),
  0,
)

afterEach(() => {
  vi.unstubAllGlobals()
})

function listSources(request: Request): Response {
  const status = new URL(request.url).searchParams.getAll('status')
  const items = status.includes('pending')
    ? pendingSources
    : sources.filter((source) => status.length === 0 || status.includes(source.status))
  return json({ items, next_cursor: null })
}

describe('sources', () => {
  it('lists pending decisions and sources with their health', async () => {
    loggedInApi({ 'GET /api/v1/sources': listSources })
    renderApp('/sources')

    const pending = await screen.findByRole('region', { name: 'Waiting for a decision' })
    expect(within(pending).getByText('Small Models Weekly')).toBeInTheDocument()
    const all = screen.getByRole('region', { name: 'All sources' })
    expect(
      within(all).getByText(/Failing since .*HTTP 503 Service Unavailable/),
    ).toBeInTheDocument()
    const { articles, shown, opened } = busiest.activity
    expect(
      within(all).getByText(
        `30 days: ${String(articles)} articles, ${String(shown)} shown, ${String(opened)} opened`,
      ),
    ).toBeInTheDocument()
  })

  it('approves a pending source', async () => {
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'PATCH /api/v1/sources/:id': () => json({ ...planner, status: 'active' }),
    })
    const user = userEvent.setup()
    renderApp('/sources')

    await user.click(await screen.findByRole('button', { name: `Read it: ${planner.name}` }))

    await vi.waitFor(() => {
      expect(api.sent('PATCH /api/v1/sources/:id')).toHaveLength(1)
    })
    const request = nth(api.sent('PATCH /api/v1/sources/:id'), 0)
    expect(request.url).toMatch(new RegExp(`/sources/${String(planner.id)}$`))
    expect(await request.json()).toEqual({ status: 'active' })
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-1')
  })

  it('filters by status', async () => {
    const api = loggedInApi({ 'GET /api/v1/sources': listSources })
    const user = userEvent.setup()
    renderApp('/sources')

    await user.selectOptions(await screen.findByLabelText('Show'), 'muted')

    const all = screen.getByRole('region', { name: 'All sources' })
    expect(await within(all).findByText('Webinar Wire')).toBeInTheDocument()
    expect(within(all).queryByText('Tidewater Data')).not.toBeInTheDocument()
    const last = api.sent('GET /api/v1/sources').at(-1) ?? new Request('http://localhost/none')
    expect(new URL(last.url).searchParams.getAll('status')).toEqual(['muted'])
  })

  it('adds a source from any page and reports a missing feed', async () => {
    const added: SourceOut = { ...nth(sources, 0), id: 9, name: 'A Blog' }
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'POST /api/v1/sources': async (request) => {
        const body = (await request.clone().json()) as { url: string }
        return body.url === 'blog.example/post'
          ? json(added, 201)
          : problem(404, 'Not Found', `no RSS or Atom feed found for ${body.url}`)
      },
    })
    const user = userEvent.setup()
    renderApp('/sources')

    const url = await screen.findByLabelText('Feed or any page of the site')
    await user.type(url, 'nofeed.example')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText('no RSS or Atom feed found for nofeed.example')).toBeVisible()
    expect(url).toHaveValue('nofeed.example')

    await user.clear(url)
    await user.type(url, 'blog.example/post')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText('Added A Blog.')).toBeInTheDocument()
    expect(url).toHaveValue('')
    expect(await api.sent('POST /api/v1/sources')[1]?.json()).toEqual({ url: 'blog.example/post' })
  })
})
