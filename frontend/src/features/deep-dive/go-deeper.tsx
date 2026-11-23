import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  listArticleDivesOptions,
  listArticleDivesQueryKey,
  startDiveMutation,
} from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { ACTIVE_REFETCH_MS, isActive } from './lib'

/** Under a brief: ask for a deep dive (with an optional focus) and see this article's. */
export function GoDeeper({ articleId }: { articleId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [focus, setFocus] = useState('')
  const path = { path: { article_id: articleId } }
  const dives = useQuery({
    ...listArticleDivesOptions(path),
    refetchInterval: (query) =>
      query.state.data?.items.some(isActive) ? ACTIVE_REFETCH_MS : false,
  })
  const start = useMutation({
    ...startDiveMutation(),
    onSuccess: async () => {
      setFocus('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: listArticleDivesQueryKey(path) }),
        queryClient.invalidateQueries({ queryKey: [{ _id: 'listDives' }] }),
      ])
    },
  })
  const canStart = dives.data?.can_start ?? false

  return (
    <section aria-labelledby="go-deeper" className="mx-auto mt-8 max-w-prose border-t pt-6">
      <h2 id="go-deeper" className="text-base font-semibold">
        {t('deepDive.goDeeper')}
      </h2>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault()
          start.mutate({ ...path, body: { focus } })
        }}
      >
        <Input
          aria-label={t('deepDive.focusLabel')}
          placeholder={t('deepDive.focusPlaceholder')}
          maxLength={300}
          value={focus}
          disabled={!canStart}
          onChange={(event) => {
            setFocus(event.target.value)
          }}
        />
        <Button type="submit" disabled={!canStart || start.isPending}>
          {t('deepDive.start')}
        </Button>
      </form>
      {dives.data && !dives.data.can_start && dives.data.reason ? (
        <p className="mt-2 text-sm text-muted-foreground">{dives.data.reason}</p>
      ) : null}
      {start.isError ? (
        <div className="mt-3">
          <ProblemMessage error={start.error} />
        </div>
      ) : null}
      {dives.data && dives.data.items.length > 0 ? (
        <ul className="mt-4 grid gap-1 text-sm">
          {dives.data.items.map((dive) => (
            <li key={dive.id}>
              <Link
                to="/deep-dives/$id"
                params={{ id: String(dive.id) }}
                className="inline-flex gap-2 py-1 hover:underline"
              >
                <span>{dive.focus || t('deepDive.noFocus')}</span>
                <span className="text-muted-foreground">{t(`deepDive.status.${dive.status}`)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
