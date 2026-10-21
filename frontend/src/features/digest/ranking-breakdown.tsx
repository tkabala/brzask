import { useTranslation } from 'react-i18next'

import type { RankingOut } from '@/client/types.gen'

/** "Why here?": the path from the day's pool to the article's place. */
export function RankingBreakdown({ ranking }: { ranking: RankingOut }) {
  const { t } = useTranslation()
  const lines: string[] = []
  if (ranking.pool !== null) lines.push(t('ranking.pool', { count: ranking.pool }))
  if (ranking.rank === null) lines.push(t('ranking.notRanked'))
  else if (ranking.ranked !== null)
    lines.push(t('ranking.rank', { rank: ranking.rank, ranked: ranking.ranked }))
  else lines.push(t('ranking.rankUnknown', { rank: ranking.rank }))
  if (ranking.top !== null) lines.push(t('ranking.top', { count: ranking.top }))
  if (ranking.deduplicated_to !== null)
    lines.push(t('ranking.deduplicated', { count: ranking.deduplicated_to }))
  if (ranking.topic !== null) lines.push(t('ranking.topic', { topic: ranking.topic }))
  if (ranking.position !== null) lines.push(t('ranking.position', { position: ranking.position }))
  const recorded = ranking.pool !== null || ranking.ranked !== null

  return (
    <section className="rounded-md bg-muted p-3" aria-label={t('ranking.title')}>
      <h3 className="font-medium">{t('ranking.title')}</h3>
      <ol className="mt-2 list-inside list-decimal space-y-1 text-muted-foreground">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
      {recorded ? (
        <p className="mt-2 text-xs text-muted-foreground">
          {t('ranking.method', {
            method: ranking.ranking_method ?? t('ranking.unknown'),
            dedup: ranking.deduplication_method ?? t('ranking.unknown'),
          })}
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">{t('ranking.notRecorded')}</p>
      )}
    </section>
  )
}
