import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { recordBriefOpenMutation } from '@/client/@tanstack/react-query.gen'
import { updateCachedArticle } from '@/features/digest/use-mark-opened'

/**
 * Records one view of an article's brief once `ready` (the brief is shown),
 * and marks the article's brief read in the cached digests. A failure (a 404
 * when the brief went away) changes nothing on the page.
 */
export function useMarkBriefOpened(articleId: number, ready: boolean): void {
  const queryClient = useQueryClient()
  const { mutate } = useMutation({
    ...recordBriefOpenMutation(),
    onSuccess: () => {
      const now = new Date().toISOString()
      updateCachedArticle(queryClient, articleId, (article) =>
        article.brief_opened_at === null ? { ...article, brief_opened_at: now } : article,
      )
    },
  })
  // Once per article, however often the page renders.
  const recorded = useRef<number | null>(null)
  useEffect(() => {
    if (!ready || recorded.current === articleId) return
    recorded.current = articleId
    mutate({ path: { article_id: articleId } })
  }, [articleId, ready, mutate])
}
