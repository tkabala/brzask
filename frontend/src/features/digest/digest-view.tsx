import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { ArticleOut, DigestOut } from '@/client/types.gen'
import { formatMoment } from '@/lib/format'

import { ArticleCard } from './article-card'

interface Props {
  digest: DigestOut
  title: string
  empty: ReactNode
  onOpen?: (article: ArticleOut) => void
  renderWhy?: (article: ArticleOut) => ReactNode
  /** When the shown copy was saved (ms since the epoch), if it is not live. */
  savedAt?: number
}

/** A day's digest as cards, in order, or what to show when there is none. */
export function DigestView({ digest, title, empty, onOpen, renderWhy, savedAt }: Props) {
  const { t, i18n } = useTranslation()
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {savedAt !== undefined ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {t('offline.savedAt', {
            time: formatMoment(new Date(savedAt).toISOString(), i18n.resolvedLanguage ?? 'en'),
          })}
        </p>
      ) : null}
      {digest.articles.length === 0 ? (
        <div className="mt-2 text-muted-foreground">{empty}</div>
      ) : (
        <ol className="mt-6 grid gap-4">
          {digest.articles.map((article) => (
            <li key={article.id}>
              <ArticleCard
                article={article}
                {...(onOpen ? { onOpen } : {})}
                {...(renderWhy ? { renderWhy: () => renderWhy(article) } : {})}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
