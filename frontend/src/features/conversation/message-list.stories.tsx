import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ConversationMessageOut } from '@/client/types.gen'
import { conversations } from '@/demo/data'

import { MessageList } from './message-list'

const demo = conversations[0]
if (!demo) throw new Error('no demo conversation')
const [, , question, answer] = demo.messages
if (!question || !answer) throw new Error('the demo conversation has two exchanges')
const lastAs = (fields: Partial<ConversationMessageOut>) => [
  ...demo.messages.slice(0, 3),
  { ...answer, ...fields },
]

const meta = {
  title: 'Screens/Conversation',
  component: MessageList,
  args: {
    messages: demo.messages,
    sources: demo.sources,
    canAsk: true,
    webSearch: true,
    onAsk: () => undefined,
    onRetry: () => undefined,
    onSearch: () => undefined,
  },
} satisfies Meta<typeof MessageList>

export default meta
type Story = StoryObj<typeof meta>

/** Two exchanges, the second answered after a search; tap a number for its source. */
export const Answered: Story = {}

/** The question is shown at once; its answer is being written. */
export const Writing: Story = { args: { messages: lastAs({ status: 'answering', answer: null }) } }

/** A search round in progress: the earlier answer stays visible. */
export const Searching: Story = { args: { messages: lastAs({ status: 'searching' }) } }

/** The material does not answer: the search is offered as the main action. */
export const NotEnough: Story = {
  args: {
    messages: lastAs({
      searched: false,
      answer: {
        paragraphs: [{ text: 'The article does not say how the proxy is priced.', sources: [1] }],
        enough: false,
        suggestions: [],
      },
    }),
  },
}

/** Without a configured web search, the round searches the archive only. */
export const ArchiveOnly: Story = { args: { webSearch: false } }

/** A search that found nothing new keeps the answer with its note. */
export const NothingNew: Story = {
  args: { messages: lastAs({ searched: false, note: 'The search found nothing new.' }) },
}

/** Failed, with the reason and "Try again". */
export const Failed: Story = {
  args: {
    messages: lastAs({ status: 'failed', answer: null, error: 'the model took too long' }),
  },
}
