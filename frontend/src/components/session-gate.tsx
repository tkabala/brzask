import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { getSessionStateOptions } from '@/client/@tanstack/react-query.gen'
import type { SessionOut } from '@/client/types.gen'
import { LoginForm } from '@/components/login-form'
import { ProblemMessage } from '@/components/problem-message'
import { setCsrfToken } from '@/lib/api'

/** Shows `children` once the API may be used, else the way to log in. */
export function SessionGate({ children }: { children: (session: SessionOut) => ReactNode }) {
  const { t } = useTranslation()
  const session = useQuery(getSessionStateOptions())

  if (session.isPending) return null
  if (session.isError) {
    return <ProblemMessage error={session.error} onRetry={() => void session.refetch()} />
  }
  const state = session.data
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
