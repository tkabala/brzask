import { useQuery } from '@tanstack/react-query'

import { getArticleRankingOptions } from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'

import { RankingBreakdown } from './ranking-breakdown'

/** Fetches the breakdown when the reader asks "why here?". */
export function RankingPanel({ articleId }: { articleId: number }) {
  const ranking = useQuery(getArticleRankingOptions({ path: { article_id: articleId } }))
  if (ranking.isPending) return null
  if (ranking.isError) return <ProblemMessage error={ranking.error} />
  return <RankingBreakdown ranking={ranking.data} />
}
