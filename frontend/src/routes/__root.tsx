import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  Outlet,
  type ErrorComponentProps,
} from '@tanstack/react-router'

import { AppHeader } from '@/components/app-header'
import { ProblemMessage } from '@/components/problem-message'
import { SessionGate } from '@/components/session-gate'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  errorComponent: RouteError,
})

function RootLayout() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <SessionGate>
        {(session) => (
          <>
            <AppHeader session={session} />
            <main className="mx-auto max-w-2xl px-4 py-8">
              <Outlet />
            </main>
          </>
        )}
      </SessionGate>
    </div>
  )
}

/** Anything a page throws, problems from the API included. */
function RouteError({ error, reset }: ErrorComponentProps) {
  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <ProblemMessage error={error} onRetry={reset} />
    </main>
  )
}
