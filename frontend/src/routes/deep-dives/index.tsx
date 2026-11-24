import { useInfiniteQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { listDivesInfiniteOptions } from '@/client/@tanstack/react-query.gen'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { DeepDiveList } from '@/features/deep-dive/deep-dive-view'
import { ACTIVE_REFETCH_MS } from '@/features/deep-dive/lib'
import { FIRST_PAGE, nextCursor } from '@/lib/pages'

export const Route = createFileRoute('/deep-dives/')({
  component: DeepDivesPage,
})

function DeepDivesPage() {
  const { t } = useTranslation()
  // Every page, not only the first; refetched every 5 s while one is being written.
  const dives = useInfiniteQuery({
    ...listDivesInfiniteOptions(),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextCursor,
    refetchInterval: (query) =>
      (query.state.data?.pages[0]?.active ?? 0) > 0 ? ACTIVE_REFETCH_MS : false,
  })
  if (dives.isPending) return <Pending query={dives} />
  if (dives.isError)
    return <ProblemMessage error={dives.error} onRetry={() => void dives.refetch()} />
  return (
    <section className="mx-auto max-w-prose">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">{t('app.nav.deepDives')}</h1>
      <DeepDiveList
        items={dives.data.pages.flatMap((page) => page.items)}
        hasMore={dives.hasNextPage}
        onMore={() => void dives.fetchNextPage()}
      />
    </section>
  )
}
