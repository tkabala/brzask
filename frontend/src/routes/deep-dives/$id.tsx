import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

import {
  getDiveOptions,
  readDiveMutation,
  retryDiveMutation,
} from '@/client/@tanstack/react-query.gen'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { DeepDiveView } from '@/features/deep-dive/deep-dive-view'
import { ACTIVE_REFETCH_MS, isActive } from '@/features/deep-dive/lib'

export const Route = createFileRoute('/deep-dives/$id')({
  component: DeepDivePage,
})

function DeepDivePage() {
  const { id } = Route.useParams()
  const diveId = Number(id)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const dive = useQuery({
    ...getDiveOptions({ path: { dive_id: diveId } }),
    refetchInterval: (query) =>
      query.state.data && isActive(query.state.data) ? ACTIVE_REFETCH_MS : false,
  })
  const read = useMutation({
    ...readDiveMutation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [{ _id: 'listDives' }] }),
  })
  const retry = useMutation({
    ...retryDiveMutation(),
    onSuccess: async (next) => {
      await queryClient.invalidateQueries({ queryKey: [{ _id: 'listDives' }] })
      await navigate({ to: '/deep-dives/$id', params: { id: String(next.id) } })
    },
  })
  // Opening a finished report marks it read, once.
  const marked = useRef<number | null>(null)
  const unread = dive.data?.status === 'done' && dive.data.read_at === null
  useEffect(() => {
    if (unread && marked.current !== diveId) {
      marked.current = diveId
      read.mutate({ path: { dive_id: diveId } })
    }
  }, [unread, diveId, read])

  if (dive.isPending) return <Pending query={dive} />
  if (dive.isError) return <ProblemMessage error={dive.error} onRetry={() => void dive.refetch()} />
  return (
    <DeepDiveView
      dive={dive.data}
      retrying={retry.isPending}
      onRetry={() => {
        retry.mutate({ path: { dive_id: diveId } })
      }}
    />
  )
}
