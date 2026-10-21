import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import { runs, status } from '@/demo/data'

import { StatusView } from './status-view'

const meta = {
  title: 'Screens/Status',
  component: StatusView,
  args: { status, runs, hasMore: true, onMore: fn(), onPause: fn(), onResume: fn() },
} satisfies Meta<typeof StatusView>

export default meta
type Story = StoryObj<typeof meta>

export const Running: Story = {}
export const Paused: Story = {
  args: { status: { ...status, paused_until: '2026-11-02T00:00:00Z' } },
}
export const NewInstance: Story = {
  args: {
    status: {
      ...status,
      articles: { total: 0, shown: 0, opened: 0 },
      last_digest: null,
      last_runs: { digest: null, review: null, visited: null, discovery: null },
      embeddings: {},
    },
    runs: [],
    hasMore: false,
  },
}
