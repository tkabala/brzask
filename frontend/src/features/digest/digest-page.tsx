import type { QueryKey, UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import type { DigestOut } from '@/client/types.gen'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { SignInAgain } from '@/components/sign-in-again'
import { useOnline } from '@/lib/online'

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
  const online = useOnline()

  if (digest.isPending) return <Pending query={digest} />
  // A saved copy beats an error: the server may only be out of reach.
  if (digest.isError && digest.data === undefined) {
    return <ProblemMessage error={digest.error} onRetry={() => void digest.refetch()} />
  }
  const saved = !online || digest.isError
  return (
    <DigestView
      digest={digest.data}
      {...(saved ? { savedAt: digest.dataUpdatedAt } : {})}
      // Online yet no answer from brzask: perhaps a proxy's login ran out.
      {...(saved && online ? { savedNote: <SignInAgain /> } : {})}
      title={title}
      empty={empty}
      onOpen={markOpened}
      renderWhy={(article) => <RankingPanel articleId={article.id} />}
    />
  )
}
