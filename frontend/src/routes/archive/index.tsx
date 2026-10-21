import { useInfiniteQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { listDigestsInfiniteOptions } from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { ArchiveView } from '@/features/archive/archive-view'
import { FIRST_PAGE, nextCursor } from '@/lib/pages'

export const Route = createFileRoute('/archive/')({
  component: ArchivePage,
})

function ArchivePage() {
  const days = useInfiniteQuery({
    ...listDigestsInfiniteOptions(),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextCursor,
  })
  if (days.isPending) return null
  if (days.isError) return <ProblemMessage error={days.error} onRetry={() => void days.refetch()} />
  return (
    <ArchiveView
      days={days.data.pages.flatMap((page) => page.items)}
      hasMore={days.hasNextPage}
      loadingMore={days.isFetchingNextPage}
      onMore={() => void days.fetchNextPage()}
    />
  )
}
