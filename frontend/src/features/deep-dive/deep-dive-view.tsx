import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { DeepDiveOut, DeepDiveRef, DeepDiveSource } from '@/client/types.gen'
import { Button } from '@/components/ui/button'

import { fetchMarkdown, markdownUrl } from './lib'

function Cites({ numbers }: { numbers: number[] }) {
  return numbers.map((n) => (
    <a
      key={n}
      href={`#source-${String(n)}`}
      className="ml-1 text-sm text-muted-foreground hover:underline"
    >
      [{n}]
    </a>
  ))
}

function SourceLink({ source }: { source: DeepDiveSource }) {
  if (source.open_url) return <a href={source.open_url}>{source.title}</a>
  return (
    <a href={source.url} target="_blank" rel="noopener noreferrer">
      {source.title}
    </a>
  )
}

/** False on plain-http origins, where browsers leave the clipboard out. */
const canCopy = () => typeof navigator !== 'undefined' && 'clipboard' in navigator

export function ExportButtons({ dive }: { dive: Pick<DeepDiveOut, 'id'> }) {
  const { t } = useTranslation()
  const [note, setNote] = useState<string | null>(null)
  const canShare = typeof navigator !== 'undefined' && 'share' in navigator
  // Fetched ahead, so share and copy run while the click still counts as the
  // reader's gesture (Safari refuses both once a request was awaited).
  const markdown = useQuery({
    queryKey: ['deepDiveMarkdown', dive.id],
    queryFn: () => fetchMarkdown(dive.id),
    staleTime: Infinity,
  })
  const withMarkdown = (send: (text: string) => Promise<unknown>, done?: string) => {
    const run =
      markdown.data !== undefined ? send(markdown.data) : fetchMarkdown(dive.id).then(send)
    run.then(
      () => {
        if (done) setNote(done)
      },
      (error: unknown) => {
        // Closing the share sheet is not a failure.
        if (error instanceof DOMException && error.name === 'AbortError') return
        setNote(t('deepDive.exportFailed'))
      },
    )
  }
  return (
    <div className="mt-8 flex flex-wrap gap-2">
      {canShare ? (
        <Button
          variant="outline"
          onClick={() => {
            withMarkdown((text) => navigator.share({ text }))
          }}
        >
          {t('deepDive.share')}
        </Button>
      ) : null}
      {canCopy() ? (
        <Button
          variant="outline"
          onClick={() => {
            withMarkdown((text) => navigator.clipboard.writeText(text), t('deepDive.copied'))
          }}
        >
          {t('deepDive.copy')}
        </Button>
      ) : null}
      <Button variant="outline" asChild>
        <a href={markdownUrl(dive.id)} download>
          {t('deepDive.download')}
        </a>
      </Button>
      {note ? (
        <span role="status" className="self-center text-sm text-muted-foreground">
          {note}
        </span>
      ) : null}
    </div>
  )
}

interface Props {
  dive: DeepDiveOut
  onRetry: () => void
  retrying?: boolean
}

/** A deep dive: its state while being written, else the report with its sources. */
export function DeepDiveView({ dive, onRetry, retrying = false }: Props) {
  const { t } = useTranslation()
  return (
    <article className="mx-auto max-w-prose">
      <Link
        to="/articles/$id"
        params={{ id: String(dive.article.id) }}
        className="text-sm text-muted-foreground hover:underline"
      >
        {t('deepDive.backToBrief')}
      </Link>
      <h1 className="mt-3 text-2xl leading-tight font-semibold tracking-tight">
        {dive.article.title}
      </h1>
      {dive.focus ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {t('deepDive.focus')}: {dive.focus}
        </p>
      ) : null}
      {dive.status === 'failed' ? (
        <div className="mt-5">
          <p>{t('deepDive.failed')}</p>
          {dive.error ? <p className="mt-1 text-sm text-muted-foreground">{dive.error}</p> : null}
          <Button className="mt-3" onClick={onRetry} disabled={retrying}>
            {t('deepDive.retry')}
          </Button>
        </div>
      ) : null}
      {dive.status === 'queued' || dive.status === 'running' ? (
        <p role="status" className="mt-5 text-muted-foreground">
          {t(`deepDive.status.${dive.status}`)}
        </p>
      ) : null}
      {dive.status === 'done' && dive.report ? <Report dive={dive} report={dive.report} /> : null}
    </article>
  )
}

function Report({
  dive,
  report,
}: {
  dive: DeepDiveOut
  report: NonNullable<DeepDiveOut['report']>
}) {
  const { t } = useTranslation()
  const byNumber = new Map(dive.sources.map((source) => [source.n, source]))
  return (
    <>
      {dive.thin ? (
        <p className="mt-3 text-sm text-muted-foreground">{t('deepDive.thin')}</p>
      ) : null}
      {!dive.searched_web && !dive.thin ? (
        <p className="mt-3 text-sm text-muted-foreground">{t('deepDive.noWeb')}</p>
      ) : null}
      <h2 className="mt-6 text-lg font-semibold">{t('deepDive.background')}</h2>
      {report.background.map((paragraph, i) => (
        <p key={i} className="mt-3 leading-relaxed">
          {paragraph.text}
          <Cites numbers={paragraph.sources} />
        </p>
      ))}
      <h2 className="mt-6 text-lg font-semibold">{t('deepDive.practice')}</h2>
      {report.practice.length === 0 ? (
        <p className="mt-3 text-muted-foreground">{t('deepDive.nothingPractical')}</p>
      ) : (
        <ol className="mt-3 grid list-decimal gap-3 pl-5 leading-relaxed">
          {report.practice.map((step, i) => (
            <li key={i} className="min-w-0">
              {step.text}
              <Cites numbers={step.sources} />
              {step.command ? (
                <div className="mt-2 flex items-start gap-2">
                  <pre className="min-w-0 flex-1 overflow-x-auto rounded bg-muted p-2 text-sm">
                    <code>{step.command}</code>
                  </pre>
                  {canCopy() ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        navigator.clipboard.writeText(step.command ?? '').catch(() => undefined)
                      }}
                    >
                      {t('deepDive.copyCommand')}
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {report.further.length > 0 ? (
        <>
          <h2 className="mt-6 text-lg font-semibold">{t('deepDive.further')}</h2>
          <ul className="mt-3 grid gap-2">
            {report.further.map((reading) => {
              const source = byNumber.get(reading.source)
              return source ? (
                <li key={reading.source}>
                  <SourceLink source={source} />: {reading.why}
                </li>
              ) : null
            })}
          </ul>
        </>
      ) : null}
      <h2 className="mt-6 text-lg font-semibold">{t('deepDive.sources')}</h2>
      <ol className="mt-3 grid list-decimal gap-1 pl-5 text-sm">
        {dive.sources.map((source) => (
          <li key={source.n} id={`source-${String(source.n)}`} className="break-words">
            <SourceLink source={source} />
          </li>
        ))}
      </ol>
      <ExportButtons dive={dive} />
    </>
  )
}

/** The list of deep dives, newest first; unread ones marked. */
export function DeepDiveList({
  items,
  hasMore = false,
  onMore,
}: {
  items: DeepDiveRef[]
  hasMore?: boolean
  onMore?: () => void
}) {
  const { t, i18n } = useTranslation()
  if (items.length === 0) return <p className="text-muted-foreground">{t('deepDive.empty')}</p>
  return (
    <>
      <ul className="grid gap-3">
        {items.map((dive) => {
          const unread = dive.status === 'done' && dive.read_at === null
          return (
            <li key={dive.id}>
              <Link
                to="/deep-dives/$id"
                params={{ id: String(dive.id) }}
                className={unread ? 'font-semibold hover:underline' : 'hover:underline'}
              >
                {dive.article.title}
              </Link>
              <p className="text-sm text-muted-foreground">
                {[
                  dive.focus,
                  unread ? t('deepDive.unread') : t(`deepDive.status.${dive.status}`),
                  new Date(dive.created_at).toLocaleDateString(i18n.language),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </li>
          )
        })}
      </ul>
      {hasMore ? (
        <Button variant="outline" className="mt-4" onClick={onMore}>
          {t('app.loadMore')}
        </Button>
      ) : null}
    </>
  )
}
