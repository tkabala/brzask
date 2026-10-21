import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { interests } from '@/demo/data'
import { json, problem } from '@/test/fake-api'
import { nth } from '@/test/nth'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('interests', () => {
  it('edits reader notes and keywords', async () => {
    const api = loggedInApi({
      'GET /api/v1/interests': () => json(interests),
      'PATCH /api/v1/interests/:id': () => json(interests[0]),
    })
    const user = userEvent.setup()
    renderApp('/interests')

    expect(
      await screen.findByText(
        'want: releases with benchmarks, planner internals; skip: vendor webinars',
      ),
    ).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Edit: Databases' }))
    const form = screen.getByRole('form', { name: 'Databases' })
    const notes = within(form).getByLabelText('Reader notes')
    await user.clear(notes)
    await user.type(notes, 'want: LTS releases')
    const keywords = within(form).getByLabelText('Keywords (comma-separated)')
    await user.clear(keywords)
    await user.type(keywords, 'query planner, , pgvector ,')
    await user.click(within(form).getByRole('button', { name: 'Save' }))

    await vi.waitFor(() => {
      expect(screen.queryByRole('form', { name: 'Databases' })).not.toBeInTheDocument()
    })
    const request = nth(api.sent('PATCH /api/v1/interests/:id'), 0)
    expect(request.url).toMatch(/\/interests\/1$/)
    expect(await request.json()).toEqual({
      topic: 'Databases',
      keywords: ['query planner', 'pgvector'],
      notes: 'want: LTS releases',
    })
  })

  it('turns an interest off', async () => {
    const api = loggedInApi({
      'GET /api/v1/interests': () => json(interests),
      'PATCH /api/v1/interests/:id': () => json({ ...interests[1], active: false }),
    })
    const user = userEvent.setup()
    renderApp('/interests')

    await user.click(await screen.findByRole('button', { name: 'Turn off: AI agents' }))

    await vi.waitFor(() => {
      expect(api.sent('PATCH /api/v1/interests/:id')).toHaveLength(1)
    })
    expect(await api.sent('PATCH /api/v1/interests/:id')[0]?.json()).toEqual({ active: false })
  })

  it('adds an interest and shows a conflict', async () => {
    const api = loggedInApi({
      'GET /api/v1/interests': () => json(interests),
      'POST /api/v1/interests': () =>
        problem(409, 'Conflict', "interest 'databases' already exists"),
    })
    const user = userEvent.setup()
    renderApp('/interests')

    const form = await screen.findByRole('form', { name: 'Add an interest' })
    await user.type(within(form).getByLabelText('Topic'), 'databases')
    await user.click(within(form).getByRole('button', { name: 'Add' }))

    expect(await screen.findByText("interest 'databases' already exists")).toBeInTheDocument()
    expect(await api.sent('POST /api/v1/interests')[0]?.json()).toEqual({
      topic: 'databases',
      keywords: [],
      notes: '',
    })
    expect(within(form).getByLabelText('Topic')).toHaveValue('databases')
  })
})
