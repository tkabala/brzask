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
