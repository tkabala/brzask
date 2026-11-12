import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { proposals } from '@/demo/data'
import { json, problem } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

const [mute, rename] = proposals

describe('changes', () => {
  it('lists proposals and approves or rejects them', async () => {
    const api = loggedInApi({})
    const user = userEvent.setup()
    renderApp('/changes')

    const card = await screen.findByRole('article', { name: `Mute ${String(mute?.entity)}` })
    expect(within(card).getByText('claude')).toBeInTheDocument()
    // Right under the page's h1, for screen readers' outline.
    expect(
      within(card).getByRole('heading', { level: 2, name: `Mute ${String(mute?.entity)}` }),
    ).toBeInTheDocument()
    expect(within(card).getByText(String(mute?.reason))).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Approve' }))

    await vi.waitFor(() => {
      expect(
        screen.queryByRole('article', { name: `Mute ${String(mute?.entity)}` }),
      ).not.toBeInTheDocument()
    })
    expect(api.sent(`POST /api/v1/changes/${String(mute?.id)}/approve`)).toHaveLength(1)

    const next = screen.getByRole('article', { name: `Rename ${String(rename?.entity)}` })
    await user.click(within(next).getByRole('button', { name: 'Reject' }))
    await vi.waitFor(() => {
      expect(api.sent(`POST /api/v1/changes/${String(rename?.id)}/reject`)).toHaveLength(1)
    })
  })

  it('shows why an approval was refused on its card', async () => {
    loggedInApi({
      'POST /api/v1/changes/:id/approve': () =>
        problem(409, 'Conflict', 'change 1 is out of date: status is now muted, not active'),
    })
    const user = userEvent.setup()
    renderApp('/changes')

    const card = await screen.findByRole('article', { name: `Mute ${String(mute?.entity)}` })
    await user.click(within(card).getByRole('button', { name: 'Approve' }))

    expect(
      await within(card).findByText('change 1 is out of date: status is now muted, not active'),
    ).toBeInTheDocument()
  })

  it('keeps a decision busy while another one settles', async () => {
    const answers = new Map<string, (response: Response) => void>()
    const api = loggedInApi({
      'POST /api/v1/changes/:id/approve': (request) =>
        new Promise<Response>((resolve) => {
          answers.set(new URL(request.url).pathname.split('/')[4] ?? '', resolve)
        }),
    })
    const user = userEvent.setup()
    renderApp('/changes')

    const first = await screen.findByRole('article', { name: `Mute ${String(mute?.entity)}` })
    const second = screen.getByRole('article', { name: `Rename ${String(rename?.entity)}` })
    await user.click(within(first).getByRole('button', { name: 'Approve' }))
    await user.click(within(second).getByRole('button', { name: 'Approve' }))
    await vi.waitFor(() => {
      expect(answers.size).toBe(2)
    })

    const lists = api.sent('GET /api/v1/changes').length
    answers.get(String(mute?.id))?.(json({ ...mute, status: 'applied' }))
    // The first decision has settled once the list was asked for again.
    await vi.waitFor(() => {
      expect(api.sent('GET /api/v1/changes').length).toBeGreaterThan(lists)
    })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(within(second).getByRole('button', { name: 'Approve' })).toBeDisabled()
    answers.get(String(rename?.id))?.(json({ ...rename, status: 'applied' }))
  })

  it('shows sources as they are after an approval', async () => {
    const api = loggedInApi({})
    const user = userEvent.setup()
    renderApp('/sources')
    await user.click(await screen.findByRole('link', { name: /Changes/ }))
    const card = await screen.findByRole('article', { name: `Mute ${String(mute?.entity)}` })
    await user.click(within(card).getByRole('button', { name: 'Approve' }))
    await vi.waitFor(() => {
      expect(api.sent(`POST /api/v1/changes/${String(mute?.id)}/approve`)).toHaveLength(1)
    })
    const before = api.sent('GET /api/v1/sources').length

    await user.click(screen.getByRole('link', { name: 'Sources' }))

    await vi.waitFor(() => {
      expect(api.sent('GET /api/v1/sources').length).toBeGreaterThan(before)
    })
  })

  it('says when nothing waits', async () => {
    loggedInApi({ 'GET /api/v1/changes': () => json([]) })
    renderApp('/changes')

    expect(await screen.findByText('No changes wait for approval.')).toBeInTheDocument()
  })

  it('counts waiting changes in the navigation', async () => {
    loggedInApi({})
    renderApp('/')

    const link = await screen.findByRole('link', { name: /Changes/ })
    expect(
      await within(link).findByLabelText(`Waiting for approval: ${String(proposals.length)}`),
    ).toBeInTheDocument()
  })

  it('shows no count when nothing waits', async () => {
    loggedInApi({ 'GET /api/v1/changes': () => json([]) })
    renderApp('/')

    const link = await screen.findByRole('link', { name: 'Changes' })
    expect(within(link).queryByLabelText(/Waiting for approval/)).not.toBeInTheDocument()
  })
})
