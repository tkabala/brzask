import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'

import { searchResults } from '@/demo/data'

import { SearchView } from './search-view'

const meta = {
  title: 'Screens/Search',
  component: SearchView,
  args: { query: '', results: null, onSearch: fn() },
} satisfies Meta<typeof SearchView>

export default meta
type Story = StoryObj<typeof meta>

export const Start: Story = {}
export const Results: Story = { args: { query: 'new Postgres features', results: searchResults } }
export const NothingClose: Story = {
  args: { query: 'knitting', results: { ...searchResults, items: [] } },
}
