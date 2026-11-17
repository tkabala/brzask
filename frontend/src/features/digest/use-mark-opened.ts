import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import type { ArticleOut, BriefOut, DigestOut } from '@/client/types.gen'
import { operationId } from '@/lib/offline-cache'

const DIGESTS = new Set(['getTodayDigest', 'getDigest'])
const BRIEF = 'getBrief'

/** Changes an article wherever the cache holds it: in any digest and in its brief. */
export function updateCachedArticle(
  queryClient: QueryClient,
  id: number,
  change: (article: ArticleOut) => ArticleOut,
): void {
  const update = (article: ArticleOut) => (article.id === id ? change(article) : article)
  queryClient.setQueriesData<DigestOut>(
    { predicate: (query) => DIGESTS.has(operationId(query.queryKey) as string) },
    (digest) => (digest ? { ...digest, articles: digest.articles.map(update) } : digest),
  )
  queryClient.setQueriesData<BriefOut>(
    { predicate: (query) => operationId(query.queryKey) === BRIEF },
    (brief) => (brief ? { ...brief, article: update(brief.article) } : brief),
  )
}

/** Marks an article opened in the cached digests right away; the server records
 * the open when the browser follows its link, and a later refetch agrees. */
export function useMarkOpened() {
  const queryClient = useQueryClient()
  return useCallback(
    (opened: ArticleOut) => {
      if (opened.opened_at !== null) return
      const now = new Date().toISOString()
      updateCachedArticle(queryClient, opened.id, (article) =>
        article.opened_at === null ? { ...article, opened_at: now } : article,
      )
    },
    [queryClient],
  )
}
