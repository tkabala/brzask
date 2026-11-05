/**
 * A saved copy of the session and today's digest, so the installed app shows
 * today's 7 without a connection. Nothing else is kept: other pages go stale
 * quickly, and the copy is removed on logout and whenever the server no
 * longer knows the reader.
 */
import type { Query, QueryClient, QueryKey } from '@tanstack/react-query'
import type {
  PersistedClient,
  Persister,
  PersistQueryClientOptions,
} from '@tanstack/react-query-persist-client'

export const CACHE_KEY = 'brzask-cache'
// A week covers a trip offline; the copy is today's digest of the day it was saved.
export const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

const SESSION = 'getSessionState'
const TODAY = 'getTodayDigest'
const SAVED = new Set([SESSION, TODAY])

/** The generated query keys start with `{ _id: operation id, baseUrl, … }`. */
function operationId(key: QueryKey): unknown {
  const first: unknown = key[0]
  return typeof first === 'object' && first !== null ? (first as { _id?: unknown })._id : undefined
}

function isToday(query: Query): boolean {
  return operationId(query.queryKey) === TODAY
}

export function shouldSave(query: Query): boolean {
  return SAVED.has(operationId(query.queryKey) as string) && query.state.status === 'success'
}

/** The browser's storage, or none where it is blocked (some private modes throw). */
export function browserStorage(): Storage | undefined {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

/** The session minus its CSRF token, which only the live session may hand out. */
function withoutCsrf(client: PersistedClient): PersistedClient {
  const queries = client.clientState.queries.map((query) => {
    if (operationId(query.queryKey) !== SESSION || query.state.data === undefined) return query
    const session = query.state.data as Record<string, unknown>
    return { ...query, state: { ...query.state, data: { ...session, csrf_token: null } } }
  })
  return { ...client, clientState: { ...client.clientState, queries } }
}

/**
 * Writes at once on every change, unthrottled: a delayed write could put a
 * digest back after a logout removed it. It skips writes that change nothing.
 */
export function createPersister(storage: Storage | undefined = browserStorage()): Persister {
  let written: string | null = null
  return {
    persistClient: (client) => {
      if (storage === undefined) return
      const text = JSON.stringify(withoutCsrf(client))
      if (text === written) return
      try {
        storage.setItem(CACHE_KEY, text)
        written = text
      } catch {
        // Storage full or blocked: the app works, only without the offline copy.
      }
    },
    restoreClient: () => {
      try {
        const text = storage?.getItem(CACHE_KEY)
        return text ? (JSON.parse(text) as PersistedClient) : undefined
      } catch {
        return undefined
      }
    },
    removeClient: () => {
      written = null
      try {
        storage?.removeItem(CACHE_KEY)
      } catch {
        // Nothing saved where nothing can be stored.
      }
    },
  }
}

export function persistOptions(
  persister: Persister,
): Omit<PersistQueryClientOptions, 'queryClient'> {
  return {
    persister,
    maxAge: MAX_AGE_MS,
    // A new release may change what the API answers; its copy starts afresh.
    buster: __APP_VERSION__,
    dehydrateOptions: { shouldDehydrateQuery: shouldSave },
  }
}

/** Removes the saved copy and today's digest from memory, so neither outlives the session. */
export function forgetSaved(
  queryClient: QueryClient,
  storage: Storage | undefined = browserStorage(),
): void {
  queryClient.removeQueries({ predicate: isToday })
  try {
    storage?.removeItem(CACHE_KEY)
  } catch {
    // Nothing saved where nothing can be stored.
  }
}
