import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { DeepDiveOut } from '@/client/types.gen'
import { briefs, deepDives } from '@/demo/data'
import { json, problem } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

const found = deepDives.find((d) => d.status === 'done')
if (!found) throw new Error('no finished demo dive')
const done: DeepDiveOut = found
const briefed = briefs[0]?.article
if (!briefed) throw new Error('no demo brief')

describe('go deeper', () => {
  it('starts a dive with the typed focus', async () => {
    const api = loggedInApi({})
    renderApp(`/articles/${String(briefed.id)}`)

    const input = await screen.findByRole('textbox', { name: 'What to focus on' })
    await waitFor(() => {
      expect(input).toBeEnabled()
    })
    await userEvent.type(input, 'for Proxmox')
    await userEvent.click(screen.getByRole('button', { name: 'Write a report' }))

    await waitFor(() => {
      expect(api.sent('POST /api/v1/articles/:id/deep-dives')).toHaveLength(1)
    })
    const [request] = api.sent('POST /api/v1/articles/:id/deep-dives')
    expect(await request?.json()).toEqual({ focus: 'for Proxmox' })
    expect(await screen.findByRole('link', { name: /for Proxmox/ })).toBeInTheDocument()
  })

  it('starts one without a focus', async () => {
    const api = loggedInApi({})
    renderApp(`/articles/${String(briefed.id)}`)
    const button = await screen.findByRole('button', { name: 'Write a report' })
    await waitFor(() => {
      expect(button).toBeEnabled()
    })
    await userEvent.click(button)
    await waitFor(() => {
      expect(api.sent('POST /api/v1/articles/:id/deep-dives')).toHaveLength(1)
    })
    expect(await api.sent('POST /api/v1/articles/:id/deep-dives')[0]?.json()).toEqual({ focus: '' })
  })

  it('is disabled with the reason when it cannot start', async () => {
    loggedInApi({
      'GET /api/v1/articles/:id/deep-dives': () =>
        json({ items: [], can_start: false, reason: 'the daily spending limit is reached' }),
    })
    renderApp(`/articles/${String(briefed.id)}`)
    expect(await screen.findByText('the daily spending limit is reached')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Write a report' })).toBeDisabled()
  })

  it("shows the server's message for a duplicate", async () => {
    loggedInApi({
      'POST /api/v1/articles/:id/deep-dives': () =>
        problem(
          409,
          'Conflict',
          'a deep dive of this article with the same focus is already being written',
        ),
    })
    renderApp(`/articles/${String(briefed.id)}`)
    const button = await screen.findByRole('button', { name: 'Write a report' })
    await waitFor(() => {
      expect(button).toBeEnabled()
    })
    await userEvent.click(button)
    expect(await screen.findByText(/already being written/)).toBeInTheDocument()
  })
})

describe('deep dives list and badge', () => {
  it('shows the unread count in the nav and marks unread dives', async () => {
    loggedInApi({})
    renderApp('/deep-dives')
    const nav = await screen.findByRole('navigation')
    expect(await within(nav).findByLabelText('1 unread deep dive')).toHaveTextContent('1')
    const link = await screen.findByRole('link', { name: done.article.title })
    expect(link).toHaveClass('font-semibold')
    expect(screen.getByText(/Unread/)).toBeInTheDocument()
  })

  it('hides the badge when nothing is unread', async () => {
    loggedInApi({
      'GET /api/v1/deep-dives': () => json({ items: [], next_cursor: null, unread: 0, active: 0 }),
    })
    renderApp('/deep-dives')
    expect(await screen.findByText(/No deep dives yet/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/unread deep dive/)).not.toBeInTheDocument()
  })
})

describe('deep dives list paging', () => {
  it('loads the next page on request', async () => {
    const [first, second] = deepDives
    if (!first || !second) throw new Error('two demo dives needed')
    const api = loggedInApi({
      'GET /api/v1/deep-dives': (request) =>
        new URL(request.url).searchParams.get('cursor') === 'next'
          ? json({ items: [second], next_cursor: null, unread: 0, active: 0 })
          : json({ items: [first], next_cursor: 'next', unread: 0, active: 0 }),
    })
    renderApp('/deep-dives')
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('link', { name: second.article.title })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
    expect(api.sent('GET /api/v1/deep-dives').length).toBeGreaterThanOrEqual(2)
  })
})

describe('deep dive page', () => {
  it('renders the report with its sources and marks it read once', async () => {
    const api = loggedInApi({})
    renderApp(`/deep-dives/${String(done.id)}`)

    expect(await screen.findByRole('heading', { name: 'Background' })).toBeInTheDocument()
    const report = done.report
    if (!report) throw new Error('demo dive without a report')
    for (const paragraph of report.background) {
      expect(screen.getByText(paragraph.text)).toBeInTheDocument()
    }
    const command = report.practice[0]?.command ?? ''
    expect(screen.getByText(command).closest('pre')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Further reading' })).toBeInTheDocument()

    const cite = screen.getAllByRole('link', { name: '[3]' })[0]
    expect(cite).toHaveAttribute('href', '#source-3')
    const web = screen.getAllByRole('link', { name: 'Upgrade guide' })[0]
    expect(web).toHaveAttribute('target', '_blank')
    expect(web).toHaveAttribute('rel', 'noopener noreferrer')
    const archive = screen.getAllByRole('link', { name: 'The previous release' })[0]
    expect(archive).toHaveAttribute('href', `/open?id=${String(briefed.id)}`)
    expect(screen.getByRole('link', { name: 'Download .md' })).toHaveAttribute(
      'href',
      expect.stringMatching(/\/deep-dives\/1\/markdown$/) as string,
    )

    await waitFor(() => {
      expect(api.sent('POST /api/v1/deep-dives/:id/read')).toHaveLength(1)
    })
  })

  it('copies the Markdown to the clipboard', async () => {
    loggedInApi({})
    const user = userEvent.setup()
    renderApp(`/deep-dives/${String(done.id)}`)
    await user.click(await screen.findByRole('button', { name: 'Copy as Markdown' }))
    expect(await screen.findByText('Copied')).toBeInTheDocument()
    expect(await navigator.clipboard.readText()).toBe(`# ${done.article.title}\n`)
  })

  it('says so when the export cannot be read', async () => {
    loggedInApi({
      'GET /api/v1/deep-dives/:id/markdown': () => problem(500, 'Internal Server Error', 'boom'),
    })
    const user = userEvent.setup()
    renderApp(`/deep-dives/${String(done.id)}`)
    await user.click(await screen.findByRole('button', { name: 'Copy as Markdown' }))
    expect(await screen.findByText('Could not export it.')).toBeInTheDocument()
  })

  it('offers share only where the browser can share', async () => {
    loggedInApi({})
    renderApp(`/deep-dives/${String(done.id)}`)
    await screen.findByRole('button', { name: 'Copy as Markdown' })
    expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument()
  })

  it('shows a running dive and refetches until it is ready', async () => {
    let calls = 0
    const running = { ...done, status: 'running', report: null, sources: [], finished_at: null }
    loggedInApi({
      'GET /api/v1/deep-dives/:id': () => {
        calls += 1
        return json(calls === 1 ? running : done)
      },
    })
    renderApp(`/deep-dives/${String(done.id)}`)
    expect(await screen.findByText('Writing…')).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: 'Background' }, { timeout: 8000 }),
    ).toBeInTheDocument()
  }, 10_000)

  it('offers to try a failed dive again', async () => {
    const failed = { ...done, id: 9, status: 'failed', report: null, error: 'LLMError: down' }
    const api = loggedInApi({
      'GET /api/v1/deep-dives/9': () => json(failed),
      'POST /api/v1/deep-dives/9/retry': () =>
        json({ ...failed, id: 10, status: 'queued', error: null }, 202),
    })
    renderApp('/deep-dives/9')
    expect(await screen.findByText('LLMError: down')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => {
      expect(api.sent('POST /api/v1/deep-dives/9/retry')).toHaveLength(1)
    })
  })
})
