import { type SubmitEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { RunKind, RunOut, StatusOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatDay, formatMoment, nextDay, runCost, seconds } from '@/lib/format'
import { cn } from '@/lib/utils'

const KINDS: RunKind[] = ['digest', 'review', 'visited', 'discovery']

interface Props {
  status: StatusOut
  runs: RunOut[]
  hasMore: boolean
  onMore?: () => void
  /** `until` is the start of the chosen day, in the reader's time zone. */
  onPause: (until: Date) => void
  onResume: () => void
  busy?: boolean
}

function RunLine({ run }: { run: RunOut }) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const took = seconds(run.started_at, run.finished_at)
  const cost = runCost(run.stats)
  return (
    <div className="grid gap-0.5 text-sm">
      <div className="flex flex-wrap gap-x-2">
        <span>{formatMoment(run.started_at, language)}</span>
        <span
          className={cn(run.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}
        >
          {t(`status.runStatus.${run.status}`)}
        </span>
        {run.dry_run ? <span className="text-muted-foreground">{t('status.dryRun')}</span> : null}
        {took !== null ? (
          <span className="text-muted-foreground">{t('status.duration', { seconds: took })}</span>
        ) : null}
        {cost !== null ? (
          <span className="text-muted-foreground">
            {t('status.cost', { cost: cost.toFixed(4) })}
          </span>
        ) : null}
      </div>
      {run.error ? <p className="text-destructive">{run.error}</p> : null}
    </div>
  )
}

export function StatusView({
  status,
  runs,
  hasMore,
  onMore,
  onPause,
  onResume,
  busy = false,
}: Props) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const [day, setDay] = useState('')
  const pause = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    // A date input gives YYYY-MM-DD; without a zone, Date reads it as local midnight.
    if (day) onPause(new Date(`${day}T00:00`))
  }

  return (
    <div className="grid gap-10">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">{t('status.title')}</h1>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t('status.articles')}</dt>
          <dd>{t('status.articlesLine', { ...status.articles })}</dd>
          <dt className="text-muted-foreground">{t('status.sources')}</dt>
          <dd>
            {Object.entries(status.sources)
              .map(
                ([state, count]) =>
                  `${String(count)} ${t(`sources.status.${state as keyof typeof status.sources}`)}`,
              )
              .join(', ')}
          </dd>
          <dt className="text-muted-foreground">{t('status.lastDigest')}</dt>
          <dd>{status.last_digest ? formatDay(status.last_digest, language) : t('status.none')}</dd>
          <dt className="text-muted-foreground">{t('status.embeddings')}</dt>
          <dd>{status.embedding_model}</dd>
        </dl>
      </section>

      <section aria-labelledby="pause-title">
        <h2 id="pause-title" className="text-lg font-semibold">
          {t('status.pause')}
        </h2>
        {status.paused_until ? (
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p>{t('status.pausedUntil', { until: formatMoment(status.paused_until, language) })}</p>
            <Button size="sm" variant="outline" disabled={busy} onClick={onResume}>
              {t('status.resume')}
            </Button>
          </div>
        ) : (
          <form className="mt-2 grid gap-2" onSubmit={pause}>
            <p className="text-sm text-muted-foreground">{t('status.notPaused')}</p>
            <Label htmlFor="pause-until">{t('status.pauseUntil')}</Label>
            <div className="flex gap-2">
              <Input
                id="pause-until"
                type="date"
                className="w-fit"
                // Midnight today has passed, and the server takes only a future moment.
                min={nextDay()}
                value={day}
                onChange={(event) => {
                  setDay(event.target.value)
                }}
              />
              <Button type="submit" disabled={busy || !day}>
                {t('status.pauseSubmit')}
              </Button>
            </div>
          </form>
        )}
      </section>

      <section aria-labelledby="pipelines-title">
        <h2 id="pipelines-title" className="text-lg font-semibold">
          {t('status.pipelines')}
        </h2>
        <ul className="mt-2 divide-y">
          {KINDS.map((kind) => {
            const run = status.last_runs[kind]
            return (
              <li key={kind} className="grid gap-1 py-2">
                <h3 className="font-medium">{t(`status.kind.${kind}`)}</h3>
                {run ? (
                  <RunLine run={run} />
                ) : (
                  <p className="text-sm text-muted-foreground">{t('status.never')}</p>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <section aria-labelledby="runs-title">
        <h2 id="runs-title" className="text-lg font-semibold">
          {t('status.runs')}
        </h2>
        {runs.length === 0 ? (
          <p className="mt-2 text-muted-foreground">{t('status.runsEmpty')}</p>
        ) : (
          <ul className="mt-2 divide-y">
            {runs.map((run) => (
              <li key={run.id} className="grid gap-1 py-2">
                <h3 className="text-sm font-medium">{t(`status.kind.${run.kind}`)}</h3>
                <RunLine run={run} />
              </li>
            ))}
          </ul>
        )}
        {hasMore ? (
          <Button variant="outline" className="mt-4" onClick={onMore}>
            {t('app.loadMore')}
          </Button>
        ) : null}
      </section>
    </div>
  )
}
