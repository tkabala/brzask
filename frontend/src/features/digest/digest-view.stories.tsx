import type { Meta, StoryObj } from '@storybook/react-vite'

import { digest, emptyDigest, ranking } from '@/demo/data'

import { DigestView } from './digest-view'
import { RankingBreakdown } from './ranking-breakdown'

const meta = {
  title: 'Screens/Today',
  component: DigestView,
  args: {
    digest,
    title: 'Today',
    empty: <p>No digest yet today.</p>,
    renderWhy: () => <RankingBreakdown ranking={ranking} />,
  },
} satisfies Meta<typeof DigestView>

export default meta
type Story = StoryObj<typeof meta>

export const Digest: Story = {}

export const Empty: Story = { args: { digest: emptyDigest } }
