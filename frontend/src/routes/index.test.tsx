import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'

import { routeTree } from '@/routeTree.gen'

describe('index route', () => {
  it('renders the today page at /', async () => {
    const router = createRouter({
      routeTree,
      history: createMemoryHistory({ initialEntries: ['/'] }),
    })

    render(<RouterProvider router={router} />)

    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
  })
})
