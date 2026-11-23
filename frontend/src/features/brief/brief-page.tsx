import { useQuery } from '@tanstack/react-query'

import { getArticleOptions, getBriefOptions } from '@/client/@tanstack/react-query.gen'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { GoDeeper } from '@/features/deep-dive/go-deeper'
import { useMarkOpened } from '@/features/digest/use-mark-opened'
import { ApiProblem } from '@/lib/api'

import { BriefMissing, BriefView } from './brief-view'
import { useMarkBriefOpened } from './use-mark-brief-opened'

const isNotFound = (error: unknown) => error instanceof ApiProblem && error.status === 404

/** An article's brief from the API; viewing it is recorded once. A missing
 * brief (not written yet, or the article is gone) still offers the original. */
export function BriefPage({ articleId }: { articleId: number }) {
  const valid = Number.isSafeInteger(articleId) && articleId > 0
  const path = { path: { article_id: articleId } }
  const brief = useQuery({ ...getBriefOptions(path), enabled: valid })
  const missing = !valid || isNotFound(brief.error)
  const article = useQuery({ ...getArticleOptions(path), enabled: valid && missing })
  const markOpened = useMarkOpened()
  useMarkBriefOpened(articleId, brief.isSuccess)

  if (missing) {
    if (valid && article.isPending && article.fetchStatus !== 'idle') {
      return <Pending query={article} />
    }
    return <BriefMissing article={article.data ?? null} onOpen={markOpened} />
  }
  if (brief.isPending) return <Pending query={brief} />
  if (brief.isError) {
    return <ProblemMessage error={brief.error} onRetry={() => void brief.refetch()} />
  }
  return (
    <>
      <BriefView brief={brief.data} onOpen={markOpened} />
      <GoDeeper articleId={articleId} />
    </>
  )
}
