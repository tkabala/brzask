import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import {
  addInterestMutation,
  changeInterestMutation,
  listInterestsOptions,
} from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { InterestsView } from '@/features/interests/interests-view'

export const Route = createFileRoute('/interests')({
  component: InterestsPage,
})

function InterestsPage() {
  const queryClient = useQueryClient()
  const [busyId, setBusyId] = useState<number | null>(null)
  const interests = useQuery(listInterestsOptions())
  const refresh = () => queryClient.invalidateQueries({ queryKey: [{ _id: 'listInterests' }] })
  const change = useMutation({
    ...changeInterestMutation(),
    onSettled: async () => {
      await refresh()
      setBusyId(null)
    },
  })
  const add = useMutation({ ...addInterestMutation(), onSuccess: refresh })

  if (interests.isPending) return null
  if (interests.isError) {
    return <ProblemMessage error={interests.error} onRetry={() => void interests.refetch()} />
  }
  const error = change.error ?? add.error
  return (
    <>
      {error ? (
        <div className="mb-4">
          <ProblemMessage error={error} />
        </div>
      ) : null}
      <InterestsView
        interests={interests.data}
        busyId={busyId}
        adding={add.isPending}
        onChange={(interest, body) => {
          setBusyId(interest.id)
          return change.mutateAsync({ path: { interest_id: interest.id }, body })
        }}
        onAdd={(body) => add.mutateAsync({ body })}
      />
    </>
  )
}
