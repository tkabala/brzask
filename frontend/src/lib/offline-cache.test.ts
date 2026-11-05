import { QueryClient } from '@tanstack/react-query'
import {
  persistQueryClientRestore,
  persistQueryClientSave,
} from '@tanstack/react-query-persist-client'

import {
  getSessionStateQueryKey,
  getTodayDigestQueryKey,
  listDigestsQueryKey,
} from '@/client/@tanstack/react-query.gen'
import type { DigestOut } from '@/client/types.gen'
import { loggedIn } from '@/test/fake-api'

import {
  CACHE_KEY,
  createPersister,
  forgetSaved,
  MAX_AGE_MS,
  persistOptions,
  watchReader,
} from './offline-cache'

const digest: DigestOut = { date: '2026-11-05', articles: [] }

function filledClient(): QueryClient {
  const client = new QueryClient()
  client.setQueryData(getSessionStateQueryKey(), loggedIn)
  client.setQueryData(getTodayDigestQueryKey(), digest)
  client.setQueryData(listDigestsQueryKey(), [])
  return client
}

async function save(client: QueryClient): Promise<void> {
  const options = persistOptions(createPersister(localStorage))
  await persistQueryClientSave({ queryClient: client, ...options })
}

async function restore(options = persistOptions(createPersister(localStorage))) {
  const client = new QueryClient()
  await persistQueryClientRestore({ queryClient: client, ...options })
  return client
}

beforeEach(() => {
  localStorage.clear()
})

describe('the saved copy', () => {
  it('keeps the session and today’s digest only', async () => {
    await save(filledClient())

    const restored = await restore()
    expect(restored.getQueryData(getTodayDigestQueryKey())).toEqual(digest)
    expect(restored.getQueryData(getSessionStateQueryKey())).toMatchObject({ authenticated: true })
    expect(restored.getQueryData(listDigestsQueryKey())).toBeUndefined()
  })

  it('never keeps the CSRF token', async () => {
    await save(filledClient())

    expect(localStorage.getItem(CACHE_KEY)).not.toContain('csrf-1')
    const restored = await restore()
    expect(restored.getQueryData(getSessionStateQueryKey())).toMatchObject({ csrf_token: null })
  })

  it('leaves out a digest that failed', async () => {
    const client = new QueryClient()
    const query = client.getQueryCache().build(client, { queryKey: getTodayDigestQueryKey() })
    query.setState({ status: 'error', error: new Error('down') })
    await save(client)

    const restored = await restore()
    expect(restored.getQueryData(getTodayDigestQueryKey())).toBeUndefined()
  })

  it('is dropped by another version of the app', async () => {
    await save(filledClient())

    const restored = await restore({
      ...persistOptions(createPersister(localStorage)),
      buster: 'another version',
    })
    expect(restored.getQueryData(getTodayDigestQueryKey())).toBeUndefined()
  })

  it('is dropped after seven days', async () => {
    await save(filledClient())
    vi.useFakeTimers({ now: Date.now() + MAX_AGE_MS + 1000 })
    try {
      const restored = await restore()
      expect(restored.getQueryData(getTodayDigestQueryKey())).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it('is forgotten on request, in storage and in memory', async () => {
    const client = filledClient()
    await save(client)

    forgetSaved(client, localStorage)

    expect(localStorage.getItem(CACHE_KEY)).toBeNull()
    expect(client.getQueryData(getTodayDigestQueryKey())).toBeUndefined()
  })
})

describe('another reader', () => {
  const as = (user: string) => ({ ...loggedIn, mode: 'header' as const, user })

  it('forgets the copy when the session names someone else', async () => {
    const client = filledClient()
    client.setQueryData(getSessionStateQueryKey(), as('alice'))
    await save(client)
    const stop = watchReader(client, localStorage)

    client.setQueryData(getSessionStateQueryKey(), as('bob'))

    expect(localStorage.getItem(CACHE_KEY)).toBeNull()
    expect(client.getQueryData(getTodayDigestQueryKey())).toBeUndefined()
    stop()
  })

  it('keeps it for the same reader', async () => {
    const client = filledClient()
    client.setQueryData(getSessionStateQueryKey(), as('alice'))
    await save(client)
    const stop = watchReader(client, localStorage)

    client.setQueryData(getSessionStateQueryKey(), as('alice'))

    expect(localStorage.getItem(CACHE_KEY)).not.toBeNull()
    expect(client.getQueryData(getTodayDigestQueryKey())).toEqual(digest)
    stop()
  })
})
