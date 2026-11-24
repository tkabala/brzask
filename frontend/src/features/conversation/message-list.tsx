import { useEffect, useRef } from 'react'

import type { ConversationMessageOut, ConversationSourceOut } from '@/client/types.gen'

import { Answer } from './answer'

interface Props {
  messages: ConversationMessageOut[]
  sources: ConversationSourceOut[]
  canAsk: boolean
  webSearch: boolean
  onAsk: (text: string) => void
  onRetry: (messageId: number) => void
  onSearch: (messageId: number) => void
}

/** Questions and answers, oldest first; the newest scrolled into view. */
export function MessageList({ messages, sources, onRetry, onSearch, ...rest }: Props) {
  const byNumber = new Map(sources.map((source) => [source.n, source]))
  const end = useRef<HTMLDivElement>(null)
  const last = messages.at(-1)
  const lastKey = last ? `${String(last.id)}:${last.status}` : ''
  useEffect(() => {
    // jsdom has no scrolling.
    if (lastKey && typeof end.current?.scrollIntoView === 'function') {
      end.current.scrollIntoView({ block: 'end' })
    }
  }, [lastKey])
  return (
    <>
      <ol className="grid gap-5">
        {messages.map((message) =>
          message.role === 'user' ? (
            <li
              key={message.id}
              className="ml-auto max-w-[85%] rounded-lg bg-muted px-3 py-2 break-words whitespace-pre-wrap"
            >
              {message.text}
            </li>
          ) : (
            <li key={message.id} className="min-w-0">
              <Answer
                message={message}
                sources={byNumber}
                latest={message === last}
                onRetry={() => {
                  onRetry(message.id)
                }}
                onSearch={() => {
                  onSearch(message.id)
                }}
                {...rest}
              />
            </li>
          ),
        )}
      </ol>
      <div ref={end} />
    </>
  )
}
