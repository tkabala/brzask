import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { getSessionStateOptions } from '@/client/@tanstack/react-query.gen'
import type { SessionOut } from '@/client/types.gen'
import { LoginForm } from '@/components/login-form'
import { ProblemMessage } from '@/components/problem-message'
import { setCsrfToken } from '@/lib/api'
import { forgetSaved } from '@/lib/offline-cache'

/** Shows `children` once the API may be used, else the way to log in. */
export function SessionGate({ children }: { children: (session: SessionOut) => ReactNode }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const session = useQuery(getSessionStateOptions())
  const loggedOut = session.data?.authenticated === false

  useEffect(() => {
    // The server no longer knows this reader: nothing of theirs stays saved.
    if (loggedOut) forgetSaved(queryClient)
  }, [loggedOut, queryClient])

  if (session.isPending) return null
  // A saved session (offline, or the server out of reach) still opens the
  // saved digest; without one there is nothing to show but the problem.
  if (session.isError && session.data === undefined) {
    return <ProblemMessage error={session.error} onRetry={() => void session.refetch()} />
  }
  const state = session.data
  // A saved session has no CSRF token: changes wait for the live session,
  // which arrives within a moment of an online start.
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
