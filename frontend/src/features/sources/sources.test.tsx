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

  it('imports an OPML file and says what came of it', async () => {
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'POST /api/v1/sources/opml': () =>
        json({
          added: [{ id: 9, name: 'A Blog', url: 'https://a.example/feed', status: 'pending' }],
          known: [],
          failed: [{ url: 'https://gone.example/feed', reason: 'no RSS or Atom feed found' }],
          unchecked: ['https://slow.example/feed'],
        }),
    })
    const user = userEvent.setup()
    renderApp('/sources')

    const opml = '<opml><body><outline xmlUrl="https://a.example/feed"/></body></opml>'
    await user.upload(
      await screen.findByLabelText('OPML file'),
      new File([opml], 'feeds.opml', { type: 'text/x-opml' }),
    )
    await user.click(screen.getByLabelText(/Read them right away/))
    await user.click(screen.getByRole('button', { name: 'Import' }))

    expect(
      await screen.findByText('Added: 1. Already sources: 0. No feed found: 1.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Not checked in time: 1. Import the same file again to continue.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/gone\.example\/feed: no RSS or Atom feed found/)).toBeInTheDocument()
    const request = nth(api.sent('POST /api/v1/sources/opml'), 0)
    expect(await request.json()).toEqual({ opml, active: true })
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-1')
  })

  it('reads an OPML file in the encoding it declares', async () => {
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'POST /api/v1/sources/opml': () => json({ added: [], known: [], failed: [], unchecked: [] }),
    })
    const user = userEvent.setup()
    renderApp('/sources')

    const head = '<?xml version="1.0" encoding="ISO-8859-2"?><opml><body><outline title="'
    const tail = '"/></body></opml>'
    // "Łódź" in ISO-8859-2.
    const title = Uint8Array.of(0xa3, 0xf3, 0x64, 0xbc)
    await user.upload(
      await screen.findByLabelText('OPML file'),
      new File([head, title, tail], 'feeds.opml', { type: 'text/x-opml' }),
    )
    await user.click(screen.getByRole('button', { name: 'Import' }))

    await screen.findByText('Added: 0. Already sources: 0. No feed found: 0.')
    const request = nth(api.sent('POST /api/v1/sources/opml'), 0)
    expect(await request.json()).toEqual({ opml: `${head}Łódź${tail}`, active: false })
  })

  it('reads an OPML file with a UTF-16 byte order mark', async () => {
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'POST /api/v1/sources/opml': () => json({ added: [], known: [], failed: [], unchecked: [] }),
    })
    const user = userEvent.setup()
    renderApp('/sources')

    const opml = '<opml><body><outline title="Łódź"/></body></opml>'
    const units = Array.from(opml, (char) => char.charCodeAt(0))
    await user.upload(
      await screen.findByLabelText('OPML file'),
      new File([Uint16Array.of(0xfeff, ...units)], 'feeds.opml', { type: 'text/x-opml' }),
    )
    await user.click(screen.getByRole('button', { name: 'Import' }))

    await screen.findByText('Added: 0. Already sources: 0. No feed found: 0.')
    const request = nth(api.sent('POST /api/v1/sources/opml'), 0)
    expect(await request.json()).toEqual({ opml, active: false })
  })

  it('exports the active sources as a file', async () => {
    const api = loggedInApi({
      'GET /api/v1/sources': listSources,
      'GET /api/v1/sources/opml': () =>
        new Response('<opml version="2.0"/>', { headers: { 'Content-Type': 'text/x-opml' } }),
    })
    const createObjectURL = vi.fn(() => 'blob:opml')
    // jsdom has no object URLs; this file runs in its own environment.
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockReturnValue(undefined)
    const user = userEvent.setup()
    renderApp('/sources')

    await user.click(await screen.findByRole('button', { name: 'Export active sources (OPML)' }))

    await vi.waitFor(() => {
      expect(click).toHaveBeenCalledOnce()
    })
    expect(api.sent('GET /api/v1/sources/opml')).toHaveLength(1)
    expect(createObjectURL).toHaveBeenCalledOnce()
    click.mockRestore()
  })
})
