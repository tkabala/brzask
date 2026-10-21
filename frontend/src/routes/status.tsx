import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import {
  deletePauseMutation,
  listRunsInfiniteOptions,
  readStatusOptions,
  setPauseMutation,
} from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { StatusView } from '@/features/status/status-view'
import { FIRST_PAGE, nextCursor } from '@/lib/pages'

// Enough to see the last week of daily and weekly runs at a glance.
const RUNS_PER_PAGE = 20

export const Route = createFileRoute('/status')({
  component: StatusPage,
})

function StatusPage() {
  const queryClient = useQueryClient()
  const status = useQuery(readStatusOptions())
  const runs = useInfiniteQuery({
    ...listRunsInfiniteOptions({ query: { limit: RUNS_PER_PAGE } }),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextCursor,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: [{ _id: 'readStatus' }] })
  const pause = useMutation({ ...setPauseMutation(), onSuccess: refresh })
  const resume = useMutation({ ...deletePauseMutation(), onSuccess: refresh })

  if (status.isPending) return null
  if (status.isError || runs.isError) {
    return (
      <ProblemMessage
        error={status.error ?? runs.error}
        onRetry={() => {
          void status.refetch()
          void runs.refetch()
        }}
      />
    )
  }
  const error = pause.error ?? resume.error
  return (
    <>
      {error ? (
        <div className="mb-4">
          <ProblemMessage error={error} />
        </div>
      ) : null}
      <StatusView
        status={status.data}
        runs={runs.data?.pages.flatMap((page) => page.items) ?? []}
        hasMore={runs.hasNextPage}
        onMore={() => void runs.fetchNextPage()}
        busy={pause.isPending || resume.isPending}
        onPause={(until) => {
          pause.mutate({ body: { until: until.toISOString() } })
        }}
        onResume={() => {
          resume.mutate({})
        }}
      />
    </>
  )
}
