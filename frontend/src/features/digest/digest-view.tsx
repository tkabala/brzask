import type { ReactNode } from 'react'

import type { ArticleOut, DigestOut } from '@/client/types.gen'

import { ArticleCard } from './article-card'

interface Props {
  digest: DigestOut
  title: string
  empty: ReactNode
  onOpen?: (article: ArticleOut) => void
  renderWhy?: (article: ArticleOut) => ReactNode
}

/** A day's digest as cards, in order, or what to show when there is none. */
export function DigestView({ digest, title, empty, onOpen, renderWhy }: Props) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
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
