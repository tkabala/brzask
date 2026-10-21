import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import type { ArticleOut, DigestOut } from '@/client/types.gen'

/** Marks an article opened in the cached digest right away; the server records
 * the open when the browser follows its link, and a later refetch agrees. */
export function useMarkOpened(queryKey: QueryKey) {
  const queryClient = useQueryClient()
  return useCallback(
    (opened: ArticleOut) => {
      if (opened.opened_at !== null) return
      const now = new Date().toISOString()
      queryClient.setQueryData<DigestOut>(queryKey, (digest) =>
        digest
          ? {
              ...digest,
              articles: digest.articles.map((article) =>
                article.id === opened.id ? { ...article, opened_at: now } : article,
              ),
            }
          : digest,
      )
    },
    [queryClient, queryKey],
  )
}
