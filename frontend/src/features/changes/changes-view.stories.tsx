import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import { proposals } from '@/demo/data'

import { ChangesView } from './changes-view'

const meta = {
  title: 'Screens/Changes',
  component: ChangesView,
  args: { changes: proposals, onApprove: fn(), onReject: fn() },
} satisfies Meta<typeof ChangesView>

export default meta
type Story = StoryObj<typeof meta>

export const Changes: Story = {}
export const Refused: Story = {
  args: {
    errors: {
      [proposals[0]?.id ?? 0]: {
        type: 'about:blank',
        title: 'Conflict',
        status: 409,
        detail: 'change 101 is out of date: status is now muted, not active',
      },
    },
  },
}
export const Empty: Story = { args: { changes: [] } }
