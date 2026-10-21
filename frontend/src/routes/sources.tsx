import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { z } from 'zod'

import {
  addSourceMutation,
  changeSourceMutation,
  listSourcesInfiniteOptions,
  listSourcesOptions,
} from '@/client/@tanstack/react-query.gen'
import type { SourceStatus } from '@/client/types.gen'
import { ProblemMessage } from '@/components/problem-message'
import { AddSourceForm } from '@/features/sources/add-source-form'
import { FILTERS } from '@/features/sources/filters'
import { SourcesView } from '@/features/sources/sources-view'
import { FIRST_PAGE, nextCursor } from '@/lib/pages'

export const Route = createFileRoute('/sources')({
  validateSearch: z.object({ show: z.enum(FILTERS).optional() }),
  component: SourcesPage,
})

function SourcesPage() {
  const { show = 'all' } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const [busyId, setBusyId] = useState<number | null>(null)

  // Pending sources have their own list above, so "all" leaves them out.
  const status: SourceStatus[] = show === 'all' ? FILTERS.filter((f) => f !== 'all') : [show]
  const pending = useQuery(listSourcesOptions({ query: { status: ['pending'], limit: 200 } }))
  const sources = useInfiniteQuery({
    ...listSourcesInfiniteOptions({ query: { status } }),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextCursor,
  })
  // Every list of sources, paged or not, filtered or not.
  const refresh = () => queryClient.invalidateQueries({ queryKey: [{ _id: 'listSources' }] })
  const change = useMutation({
    ...changeSourceMutation(),
    onSettled: async () => {
      await refresh()
      setBusyId(null)
    },
  })
  const add = useMutation({ ...addSourceMutation(), onSuccess: refresh })

  if (pending.isError || sources.isError) {
    const error = pending.error ?? sources.error
    return (
      <ProblemMessage
        error={error}
        onRetry={() => {
          void pending.refetch()
          void sources.refetch()
        }}
      />
    )
  }
  return (
    <>
      {change.isError ? (
        <div className="mb-4">
          <ProblemMessage error={change.error} />
        </div>
      ) : null}
      <SourcesView
        pending={pending.data?.items ?? []}
        sources={sources.data?.pages.flatMap((page) => page.items) ?? []}
        filter={show}
        onFilter={(filter) => void navigate({ search: { show: filter } })}
        hasMore={sources.hasNextPage}
        onMore={() => void sources.fetchNextPage()}
        busyId={busyId}
        onDecide={(source, decision) => {
          setBusyId(source.id)
          change.mutate({ path: { source_id: source.id }, body: { status: decision } })
        }}
        addForm={
          <AddSourceForm
            pending={add.isPending}
            error={add.error}
            addedName={add.data?.name ?? null}
            onAdd={(values) =>
              add.mutateAsync({
                body: { url: values.url, ...(values.name ? { name: values.name } : {}) },
              })
            }
          />
        }
      />
    </>
  )
}
