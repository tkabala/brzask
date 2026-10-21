import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { getSessionStateQueryKey } from '@/client/@tanstack/react-query.gen'

import { ApiProblem } from './api'

// Another try helps after a network hiccup or a restart, never for a 4xx.
const RETRIES = 2

function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiProblem && error.status < 500) return false
  return failures < RETRIES
}

export function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000 },
      mutations: { retry: false },
    },
    // A 401 anywhere means the session ended: ask again, and the gate shows the login.
    queryCache: new QueryCache({
      onError: (error) => {
        onError(error)
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        onError(error)
      },
    }),
  })

  function onError(error: unknown): void {
    if (error instanceof ApiProblem && error.status === 401) {
      void queryClient.invalidateQueries({ queryKey: getSessionStateQueryKey() })
    }
  }

  return queryClient
}
