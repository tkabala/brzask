/** The whole app at each route, against the demo API (MSW). */
import type { Meta, StoryObj } from '@storybook/react-vite'
import { createMemoryHistory } from '@tanstack/react-router'
import { http } from 'msw'

import { App } from '@/app'
import { emptyDigest } from '@/demo/data'
import { logOutDemo, problem, withApi } from '@/demo/handlers'
import { createQueryClient } from '@/lib/query'

function Page({ path }: { path: string }) {
  return (
    <App
      queryClient={createQueryClient()}
      history={createMemoryHistory({ initialEntries: [path] })}
    />
  )
}

const meta = {
  title: 'Pages',
  component: Page,
  parameters: { app: true, layout: 'fullscreen' },
  args: { path: '/' },
} satisfies Meta<typeof Page>

export default meta
type Story = StoryObj<typeof meta>

export const Today: Story = {}

/** Before the morning run. */
export const TodayEmpty: Story = {
  parameters: withApi(http.get('*/api/v1/digests/today', () => Response.json(emptyDigest))),
}

/** The demo password is "demo". */
export const Login: Story = {
  beforeEach: () => {
    logOutDemo()
  },
}

export const Archive: Story = { args: { path: '/archive' } }
export const ArchivedDay: Story = { args: { path: '/archive/2026-10-21' } }
export const Search: Story = { args: { path: '/search?q=postgres release' } }
export const Sources: Story = { args: { path: '/sources' } }
export const Interests: Story = { args: { path: '/interests' } }
export const Status: Story = { args: { path: '/status' } }

/** What every page shows when the API fails. */
export const ServerError: Story = {
  parameters: withApi(
    http.get('*/api/v1/digests/today', () =>
      problem(503, 'Service Unavailable', 'The database is unreachable.'),
    ),
  ),
}
