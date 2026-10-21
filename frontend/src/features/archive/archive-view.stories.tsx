import type { Meta, StoryObj } from '@storybook/react-vite'

import { days } from '@/demo/data'

import { ArchiveView } from './archive-view'

const meta = {
  title: 'Screens/Archive',
  component: ArchiveView,
  args: { days, hasMore: false },
} satisfies Meta<typeof ArchiveView>

export default meta
type Story = StoryObj<typeof meta>

export const Days: Story = {}
export const MoreToLoad: Story = { args: { hasMore: true } }
export const Empty: Story = { args: { days: [] } }
