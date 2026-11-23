import type { Meta, StoryObj } from '@storybook/react-vite'

import type { DeepDiveOut } from '@/client/types.gen'
import { deepDives } from '@/demo/data'

import { DeepDiveList, DeepDiveView } from './deep-dive-view'

function diveIn(status: DeepDiveOut['status']): DeepDiveOut {
  const dive = deepDives.find((d) => d.status === status)
  if (!dive) throw new Error(`no demo deep dive ${status}`)
  return dive
}

const done = diveIn('done')

const meta = {
  title: 'Screens/Deep dive',
  component: DeepDiveView,
  args: { dive: done, onRetry: () => undefined },
} satisfies Meta<typeof DeepDiveView>

export default meta
type Story = StoryObj<typeof meta>

/** A finished report: background, steps with a long command, further reading, sources. */
export const Ready: Story = {}

/** Being written: the page shows its state and refetches. */
export const Writing: Story = { args: { dive: diveIn('running') } }

/** Failed, with the reason and "Try again". */
export const Failed: Story = {
  args: { dive: { ...done, status: 'failed', report: null, error: 'LLMError: provider down' } },
}

/** Written from the article alone. */
export const Thin: Story = {
  args: { dive: { ...done, thin: true, searched_web: false, sources: done.sources.slice(0, 1) } },
}

/** The list, unread ones marked. */
export const List: Story = {
  render: () => <DeepDiveList items={deepDives} />,
}
