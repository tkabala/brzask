import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import {
  approveChangeMutation,
  listChangesOptions,
  rejectChangeMutation,
} from '@/client/@tanstack/react-query.gen'
import type { ChangeOut } from '@/client/types.gen'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { ChangesView } from '@/features/changes/changes-view'

export const Route = createFileRoute('/changes')({
  component: ChangesPage,
})

function ChangesPage() {
  const queryClient = useQueryClient()
  const [busyId, setBusyId] = useState<number | null>(null)
  const [errors, setErrors] = useState<Record<number, unknown>>({})
  // The same query as the count in the header, so a decision updates both.
  const changes = useQuery(listChangesOptions())
  const handlers = {
    onMutate: ({ path }: { path: { change_id: number } }) => {
      setBusyId(path.change_id)
      setErrors((current) =>
        Object.fromEntries(Object.entries(current).filter(([id]) => id !== String(path.change_id))),
      )
    },
    onError: (error: unknown, { path }: { path: { change_id: number } }) => {
      setErrors((current) => ({ ...current, [path.change_id]: error }))
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: [{ _id: 'listChanges' }] })
      setBusyId(null)
    },
  }
  const approve = useMutation({ ...approveChangeMutation(), ...handlers })
  const reject = useMutation({ ...rejectChangeMutation(), ...handlers })

  if (changes.isPending) return <Pending query={changes} />
  if (changes.isError) {
    return <ProblemMessage error={changes.error} onRetry={() => void changes.refetch()} />
  }
  const decide = (mutation: typeof approve) => (change: ChangeOut) => {
    mutation.mutate({ path: { change_id: change.id } })
  }
  return (
    <ChangesView
      changes={changes.data}
      busyId={busyId}
      errors={errors}
      onApprove={decide(approve)}
      onReject={decide(reject)}
    />
  )
}
