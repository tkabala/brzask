import { useTranslation } from 'react-i18next'

import type { SourceOut, SourceStatus } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { formatMoment } from '@/lib/format'
import { cn } from '@/lib/utils'

/** A status a reader can set: read it, stop reading it, or decline a proposal. */
export type Decision = Extract<SourceStatus, 'active' | 'muted' | 'rejected'>

interface Props {
  source: SourceOut
  onDecide?: (source: SourceOut, status: Decision) => void
  busy?: boolean
}

export function SourceItem({ source, onDecide, busy = false }: Props) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const { health, activity } = source
  const failing = health.failing_since !== null

  const actions: [Decision, string, 'default' | 'outline'][] =
    source.status === 'pending'
      ? [
          ['active', t('sources.approve'), 'default'],
          ['rejected', t('sources.reject'), 'outline'],
        ]
      : source.status === 'active'
        ? [['muted', t('sources.mute'), 'outline']]
        : [['active', t('sources.enable'), 'outline']]

  return (
    <article className="grid gap-1 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium">{source.name}</h3>
        <span
          className={cn(
            'rounded-full border px-2 text-xs',
            source.status === 'active' ? 'text-foreground' : 'text-muted-foreground',
          )}
        >
          {t(`sources.status.${source.status}`)}
        </span>
        {source.kind === 'release' ? (
          <span className="text-xs text-muted-foreground">releases</span>
        ) : null}
      </div>
      <a
        href={source.site_url ?? source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="truncate text-sm text-muted-foreground hover:underline"
      >
        {source.url}
      </a>
      {source.note ? <p className="text-sm">{source.note}</p> : null}
      {source.status !== 'pending' ? (
        <p className="text-sm text-muted-foreground">{t('sources.activity', { ...activity })}</p>
      ) : null}
      {failing ? (
        <p className="text-sm text-destructive">
          {t('sources.failing', {
            since: formatMoment(health.failing_since ?? '', language),
            error: health.fetch_error ?? '',
          })}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {health.fetched_at
            ? t('sources.lastFetched', { when: formatMoment(health.fetched_at, language) })
            : t('sources.neverFetched')}
        </p>
      )}
      {onDecide ? (
        <div className="mt-1 flex gap-2">
          {actions.map(([status, label, variant]) => (
            <Button
              key={status}
              size="sm"
              variant={variant}
              disabled={busy}
              aria-label={`${label}: ${source.name}`}
              onClick={() => {
                onDecide(source, status)
              }}
            >
              {label}
            </Button>
          ))}
        </div>
      ) : null}
    </article>
  )
}
