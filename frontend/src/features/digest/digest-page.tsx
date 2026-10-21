import type { QueryKey, UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import type { DigestOut } from '@/client/types.gen'
import { ProblemMessage } from '@/components/problem-message'

import { DigestView } from './digest-view'
import { RankingPanel } from './ranking-panel'
import { useMarkOpened } from './use-mark-opened'

/** A digest from the API: cards that mark themselves opened, with "why here?". */
export function DigestPage({
  digest,
  queryKey,
  title,
  empty,
}: {
  digest: UseQueryResult<DigestOut, unknown>
  queryKey: QueryKey
  title: string
  empty: ReactNode
}) {
  const markOpened = useMarkOpened(queryKey)

  if (digest.isPending) return null
  if (digest.isError) {
    return <ProblemMessage error={digest.error} onRetry={() => void digest.refetch()} />
  }
  return (
    <DigestView
      digest={digest.data}
      title={title}
      empty={empty}
      onOpen={markOpened}
      renderWhy={(article) => <RankingPanel articleId={article.id} />}
    />
  )
}
