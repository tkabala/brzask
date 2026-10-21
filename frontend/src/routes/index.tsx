import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { getTodayDigestOptions } from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'

export const Route = createFileRoute('/')({
  component: TodayPage,
})

function TodayPage() {
  const { t } = useTranslation()
  // Fetched here, not in a route loader: loaders run before the session gate
  // knows whether the reader is logged in.
  const digest = useQuery(getTodayDigestOptions())

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('today.title')}</h1>
      {digest.isPending ? null : digest.isError ? (
        <div className="mt-4">
          <ProblemMessage error={digest.error} onRetry={() => void digest.refetch()} />
        </div>
      ) : digest.data.articles.length === 0 ? (
        <div className="mt-2 text-muted-foreground">
          <p>{t('today.empty')}</p>
          <p className="mt-1 text-sm">{t('today.emptyHint')}</p>
        </div>
      ) : (
        <ol className="mt-6 grid gap-4">
          {digest.data.articles.map((article) => (
            <li key={article.id}>
              <a href={article.open_url} className="font-medium hover:underline">
                {article.title}
              </a>
              {article.summary ? (
                <p className="mt-1 text-sm text-muted-foreground">{article.summary}</p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
