import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type {
  ConversationMessageOut,
  ConversationParagraph,
  ConversationSourceOut,
} from '@/client/types.gen'
import { Button } from '@/components/ui/button'

/** Stored articles open through `open_url` (recording the open); web pages in a new tab. */
function SourceLink({ source }: { source: ConversationSourceOut }) {
  if (source.open_url) {
    return (
      <a href={source.open_url} target="_blank" rel="noopener" className="underline">
        {source.title}
      </a>
    )
  }
  return (
    <a href={source.url} target="_blank" rel="noopener noreferrer" className="underline">
      {source.title}
    </a>
  )
}

/** A paragraph with its source numbers; a number expands to the source's title and link. */
function Paragraph({
  paragraph,
  sources,
}: {
  paragraph: ConversationParagraph
  sources: ReadonlyMap<number, ConversationSourceOut>
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<number | null>(null)
  const shown = open === null ? undefined : sources.get(open)
  return (
    <div className="mt-2 first:mt-0">
      <p className="leading-relaxed">
        {paragraph.text}
        {paragraph.sources
          .filter((n) => sources.has(n))
          .map((n) => (
            <button
              key={n}
              type="button"
              aria-label={t('conversation.source', { n })}
              aria-expanded={open === n}
              className="ml-1 rounded px-1 align-baseline text-xs text-muted-foreground ring-1 ring-border hover:bg-muted aria-expanded:bg-muted"
              onClick={() => {
                setOpen(open === n ? null : n)
              }}
            >
              {n}
            </button>
          ))}
      </p>
      {shown ? (
        <p className="mt-1 text-sm break-words text-muted-foreground">
          [{shown.n}] <SourceLink source={shown} />
        </p>
      ) : null}
    </div>
  )
}

interface Props {
  message: ConversationMessageOut
  sources: ReadonlyMap<number, ConversationSourceOut>
  /** The conversation's last message: suggestions, retry and search act on it. */
  latest: boolean
  canAsk: boolean
  webSearch: boolean
  onAsk: (text: string) => void
  onRetry: () => void
  onSearch: () => void
}

/** One answer in its state: being written, searched for, failed or done. */
export function Answer({
  message,
  sources,
  latest,
  canAsk,
  webSearch,
  onAsk,
  onRetry,
  onSearch,
}: Props) {
  const { t } = useTranslation()
  const { answer, status } = message
  const finished = status === 'done' || status === 'failed'
  const notEnough = answer?.enough === false
  const searchLabel = webSearch ? t('conversation.searchWeb') : t('conversation.searchArchive')
  return (
    <div>
      {status === 'answering' ? (
        <p role="status" className="text-muted-foreground">
          {t('conversation.writing')}
        </p>
      ) : null}
      {answer && status !== 'answering'
        ? answer.paragraphs.map((paragraph, i) => (
            <Paragraph key={i} paragraph={paragraph} sources={sources} />
          ))
        : null}
      {status === 'searching' ? (
        <p role="status" className="mt-2 text-muted-foreground">
          {t('conversation.searching')}
        </p>
      ) : null}
      {status === 'failed' ? (
        <div className="mt-2">
          <p>{t('conversation.failed')}</p>
          {message.error ? (
            <p className="mt-1 text-sm text-muted-foreground">{message.error}</p>
          ) : null}
          {latest ? (
            <Button className="mt-2" size="sm" onClick={onRetry} disabled={!canAsk}>
              {t('conversation.retry')}
            </Button>
          ) : null}
        </div>
      ) : null}
      {message.note ? <p className="mt-2 text-sm text-muted-foreground">{message.note}</p> : null}
      {latest && finished ? (
        notEnough ? (
          <div className="mt-3">
            <p className="text-sm">{t('conversation.notEnough')}</p>
            <Button className="mt-2" size="sm" onClick={onSearch} disabled={!canAsk}>
              {searchLabel}
            </Button>
          </div>
        ) : (
          <Button
            variant="link"
            size="sm"
            className="mt-1 h-auto px-0"
            onClick={onSearch}
            disabled={!canAsk}
          >
            {searchLabel}
          </Button>
        )
      ) : null}
      {latest && status === 'done' && answer && answer.suggestions.length > 0 ? (
        <ul aria-label={t('conversation.suggestions')} className="mt-3 flex flex-wrap gap-2">
          {answer.suggestions.map((suggestion) => (
            <li key={suggestion}>
              <Button
                variant="outline"
                size="sm"
                className="h-auto py-1.5 text-left whitespace-normal"
                disabled={!canAsk}
                onClick={() => {
                  onAsk(suggestion)
                }}
              >
                {suggestion}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
