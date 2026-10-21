import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import { interests } from '@/demo/data'

import { InterestsView } from './interests-view'

const meta = {
  title: 'Screens/Interests',
  component: InterestsView,
  args: {
    interests,
    onChange: fn(async () => Promise.resolve()),
    onAdd: fn(async () => Promise.resolve()),
  },
} satisfies Meta<typeof InterestsView>

export default meta
type Story = StoryObj<typeof meta>

export const Interests: Story = {}
export const Empty: Story = { args: { interests: [] } }
