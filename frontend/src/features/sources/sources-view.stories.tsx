import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import { ApiProblem } from '@/lib/api'
import { pendingSources, sources } from '@/demo/data'

import { AddSourceForm } from './add-source-form'
import { OpmlForm } from './opml-form'
import { SourcesView } from './sources-view'

const meta = {
  title: 'Screens/Sources',
  component: SourcesView,
  args: {
    pending: pendingSources,
    sources,
    filter: 'all',
    onFilter: fn(),
    hasMore: false,
    onDecide: fn(),
    addForm: <AddSourceForm onAdd={fn(async () => Promise.resolve())} />,
    opmlForm: <OpmlForm onImport={fn(async () => Promise.resolve())} onExport={fn()} />,
  },
} satisfies Meta<typeof SourcesView>

export default meta
type Story = StoryObj<typeof meta>

export const WithPendingDecisions: Story = {}
export const NothingPending: Story = { args: { pending: [] } }
export const Deciding: Story = { args: { busyId: 4 } }
export const NoFeedFound: Story = {
  args: {
    pending: [],
    addForm: (
      <AddSourceForm
        onAdd={fn(async () => Promise.resolve())}
        error={
          new ApiProblem(404, {
            title: 'Not Found',
            status: 404,
            detail: 'no RSS or Atom feed found for https://example.com',
          })
        }
      />
    ),
  },
}
export const OpmlImported: Story = {
  args: {
    pending: [],
    opmlForm: (
      <OpmlForm
        onImport={fn(async () => Promise.resolve())}
        onExport={fn()}
        report={{
          added: [{ id: 9, name: 'A Blog', url: 'https://a.example/feed', status: 'pending' }],
          known: [{ url: 'https://b.example/feed', name: 'B', status: 'active' }],
          failed: [{ url: 'https://gone.example/feed', reason: 'no RSS or Atom feed found' }],
          unchecked: ['https://slow.example/feed'],
        }}
      />
    ),
  },
}
