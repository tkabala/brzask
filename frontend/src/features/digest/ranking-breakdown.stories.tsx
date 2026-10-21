import type { Meta, StoryObj } from '@storybook/react-vite'

import { ranking } from '@/demo/data'

import { RankingBreakdown } from './ranking-breakdown'

const meta = {
  title: 'Components/RankingBreakdown',
  component: RankingBreakdown,
  args: { ranking },
} satisfies Meta<typeof RankingBreakdown>

export default meta
type Story = StoryObj<typeof meta>

export const Recorded: Story = {}

/** A run from before its stats recorded the pool and the methods. */
export const NotRecorded: Story = {
  args: {
    ranking: {
      ...ranking,
      pool: null,
      ranked: null,
      top: null,
      deduplicated_to: null,
      ranking_method: null,
      deduplication_method: null,
      run_id: null,
    },
  },
}

export const NotRanked: Story = { args: { ranking: { ...ranking, rank: null } } }
