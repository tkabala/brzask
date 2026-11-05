import type { Meta, StoryObj } from '@storybook/react-vite'
import { onlineManager } from '@tanstack/react-query'

import { OfflineBanner } from './offline-banner'

const meta = {
  title: 'Components/Offline banner',
  component: OfflineBanner,
  beforeEach: () => {
    onlineManager.setOnline(false)
    return () => {
      onlineManager.setOnline(true)
    }
  },
} satisfies Meta<typeof OfflineBanner>

export default meta
type Story = StoryObj<typeof meta>

export const Offline: Story = {}
