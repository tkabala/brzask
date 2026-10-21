import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import type { DigestDayOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { formatDay } from '@/lib/format'

interface Props {
  days: DigestDayOut[]
  hasMore: boolean
  loadingMore?: boolean
  onMore?: () => void
}

export function ArchiveView({ days, hasMore, loadingMore = false, onMore }: Props) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('archive.title')}</h1>
      {days.length === 0 ? (
        <p className="mt-2 text-muted-foreground">{t('archive.empty')}</p>
      ) : (
        <ul className="mt-6 divide-y">
          {days.map((day) => (
            <li key={day.date} className="flex items-baseline justify-between gap-4 py-3">
              <Link to="/archive/$day" params={{ day: day.date }} className="hover:underline">
                {formatDay(day.date, language)}
              </Link>
              <span className="text-sm text-muted-foreground">
                {t('archive.articles', { count: day.articles })}
                {day.opened > 0 ? ` · ${t('archive.opened', { count: day.opened })}` : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      {hasMore ? (
        <Button variant="outline" className="mt-4" disabled={loadingMore} onClick={onMore}>
          {t('app.loadMore')}
        </Button>
      ) : null}
    </section>
  )
}
