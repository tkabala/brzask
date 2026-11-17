import type { Meta, StoryObj } from '@storybook/react-vite'

import type { BriefOut } from '@/client/types.gen'
import { articles, briefs } from '@/demo/data'

import { BriefMissing, BriefView } from './brief-view'

function briefFrom(basis: BriefOut['basis']): BriefOut {
  const brief = briefs.find((b) => b.basis === basis)
  if (!brief) throw new Error(`no demo brief from ${basis}`)
  return brief
}

const meta = {
  title: 'Screens/Brief',
  component: BriefView,
  args: { brief: briefFrom('full_text') },
} satisfies Meta<typeof BriefView>

export default meta
type Story = StoryObj<typeof meta>

/** An article briefed from its full text. */
export const TextArticle: Story = {}

/** A video briefed from its transcript, with chapters. */
export const Video: Story = { args: { brief: briefFrom('transcript') } }

/** Only the feed's description was available. */
export const DescriptionOnly: Story = { args: { brief: briefFrom('description') } }

/** No brief yet: the original is still offered. */
export const Missing: Story = {
  render: () => <BriefMissing article={articles[1] ?? null} />,
}
