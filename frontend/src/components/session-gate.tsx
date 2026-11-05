import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { getSessionStateOptions } from '@/client/@tanstack/react-query.gen'
import type { SessionOut } from '@/client/types.gen'
import { LoginForm } from '@/components/login-form'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { SignInAgain } from '@/components/sign-in-again'
import { setCsrfToken } from '@/lib/api'
import { forgetSaved } from '@/lib/offline-cache'
import { useOnline } from '@/lib/online'

/** Shows `children` once the API may be used, else the way to log in. */
export function SessionGate({ children }: { children: (session: SessionOut) => ReactNode }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const online = useOnline()
  const session = useQuery(getSessionStateOptions())
  const [startedAt] = useState(() => Date.now())
  const loggedOut = session.data?.authenticated === false

  useEffect(() => {
    // The server no longer knows this reader: nothing of theirs stays saved.
    if (loggedOut) forgetSaved(queryClient)
  }, [loggedOut, queryClient])

  if (session.isPending) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <Pending query={session} />
      </div>
    )
  }
  // A saved session is shown only once the server cannot confirm it (offline,
  // or out of reach); online, the live answer comes first.
  const saved = session.dataUpdatedAt < startedAt
  if (saved && session.isFetching) return null
  if (session.isError && session.data === undefined) {
    return (
      <div className="grid gap-3">
        <ProblemMessage error={session.error} onRetry={() => void session.refetch()} />
        {online ? <SignInAgain /> : null}
      </div>
    )
  }
  const state = session.data
  // A saved session has no CSRF token: changes need the live session.
  setCsrfToken(state.csrf_token ?? null)
  if (state.authenticated) return children(state)
  if (state.mode === 'header') {
    return (
      <section className="mx-auto mt-16 max-w-md">
        <h1 className="text-xl font-semibold">{t('proxy.title')}</h1>
        <p className="mt-2 text-muted-foreground">{t('proxy.body')}</p>
      </section>
    )
  }
  return <LoginForm />
}
