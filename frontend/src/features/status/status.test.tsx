import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { runs, status } from '@/demo/data'
import { nextDay } from '@/lib/format'
import { json } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('status', () => {
  it('shows counts, the last run of each pipeline and recent runs', async () => {
    loggedInApi({
      'GET /api/v1/status': () => json(status),
      'GET /api/v1/runs': () => json({ items: runs, next_cursor: null }),
    })
    renderApp('/status')

    expect(await screen.findByText('5345 stored, 802 shown, 36 opened')).toBeInTheDocument()
    const pipelines = screen.getByRole('region', { name: 'Pipelines' })
    expect(within(pipelines).getByText('never ran')).toBeInTheDocument()
    expect(within(pipelines).getAllByText('database is locked by another review')).toHaveLength(1)
    const recent = screen.getByRole('region', { name: 'Recent runs' })
    expect(within(recent).getByText('$0.0812')).toBeInTheDocument()
    expect(within(recent).getByText('192 s')).toBeInTheDocument()
  })

  it('pauses until the start of a chosen day', async () => {
    let paused: string | null = null
    const api = loggedInApi({
      'GET /api/v1/status': () => json({ ...status, paused_until: paused }),
      'GET /api/v1/runs': () => json({ items: [], next_cursor: null }),
      'PUT /api/v1/pause': async (request) => {
        paused = ((await request.clone().json()) as { until: string }).until
        return json({ until: paused })
      },
    })
    const user = userEvent.setup()
    renderApp('/status')

    const day = await screen.findByLabelText('Pause until')
    // Today's midnight has passed, so the first day offered is tomorrow.
    expect(day).toHaveAttribute('min', nextDay())
    await user.type(day, '2026-11-02')
    await user.click(screen.getByRole('button', { name: 'Pause' }))

    expect(await screen.findByText(/The digest is paused until/)).toBeInTheDocument()
    const body = (await api.sent('PUT /api/v1/pause')[0]?.json()) as { until: string }
    expect(new Date(body.until).getTime()).toBe(new Date('2026-11-02T00:00').getTime())
  })

  it('resumes a pause', async () => {
    let paused: string | null = '2026-11-02T00:00:00Z'
    const api = loggedInApi({
      'GET /api/v1/status': () => json({ ...status, paused_until: paused }),
      'GET /api/v1/runs': () => json({ items: [], next_cursor: null }),
      'DELETE /api/v1/pause': () => {
        paused = null
        return new Response(null, { status: 204 })
      },
    })
    const user = userEvent.setup()
    renderApp('/status')

    await user.click(await screen.findByRole('button', { name: 'Resume now' }))

    expect(await screen.findByText('The digest runs every day.')).toBeInTheDocument()
    expect(api.sent('DELETE /api/v1/pause')).toHaveLength(1)
  })
})
