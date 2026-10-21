import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { searchResults } from '@/demo/data'
import { nth } from '@/test/nth'
import { json, problem } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('search', () => {
  it('searches by meaning and shows how close each result is', async () => {
    const api = loggedInApi({ 'GET /api/v1/search': () => json(searchResults) })
    const user = userEvent.setup()
    renderApp('/search')

    await user.type(await screen.findByLabelText('What are you looking for?'), 'postgres news')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('82% similar')).toBeInTheDocument()
    const best = nth(searchResults.items, 0).article
    expect(
      screen.getByRole('link', { name: (name) => name.includes(best.title) }),
    ).toBeInTheDocument()
    const sent = new URL(api.sent('GET /api/v1/search')[0]?.url ?? '')
    expect(sent.searchParams.get('q')).toBe('postgres news')
  })

  it('runs the search in the address again', async () => {
    loggedInApi({ 'GET /api/v1/search': () => json({ ...searchResults, items: [] }) })
    renderApp('/search?q=knitting')

    expect(await screen.findByText('Nothing close to that.')).toBeInTheDocument()
    expect(screen.getByLabelText('What are you looking for?')).toHaveValue('knitting')
  })

  it('shows a failing embedding API', { timeout: 10_000 }, async () => {
    loggedInApi({
      'GET /api/v1/search': () => problem(502, 'Bad Gateway', 'embedding API failed: 503'),
    })
    renderApp('/search?q=x')

    // Server errors are tried twice more, with a delay, before they show.
    expect(
      await screen.findByText('embedding API failed: 503', {}, { timeout: 8000 }),
    ).toBeInTheDocument()
  })
})
