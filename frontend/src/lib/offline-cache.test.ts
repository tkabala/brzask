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

  it('leaves out changes waiting for a connection', async () => {
    const client = filledClient()
    client.getMutationCache().build(
      client,
      { mutationFn: () => Promise.resolve() },
      {
        context: undefined,
        data: undefined,
        error: null,
        failureCount: 0,
        failureReason: null,
        isPaused: true,
        status: 'pending',
        variables: { body: { topic: 'typed offline' } },
        submittedAt: 0,
      },
    )

    await save(client)

    expect(localStorage.getItem(CACHE_KEY)).not.toContain('typed offline')
  })

  it('is written again only when its data changed', async () => {
    const client = filledClient()
    const options = persistOptions(createPersister(localStorage))
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const now = vi.spyOn(Date, 'now')
    try {
      now.mockReturnValue(1_000)
      await persistQueryClientSave({ queryClient: client, ...options })
      now.mockReturnValue(2_000)
      await persistQueryClientSave({ queryClient: client, ...options })
      expect(setItem).toHaveBeenCalledTimes(1)

      client.setQueryData(getTodayDigestQueryKey(), { ...digest, date: '2026-11-06' })
      await persistQueryClientSave({ queryClient: client, ...options })
      expect(setItem).toHaveBeenCalledTimes(2)
    } finally {
      setItem.mockRestore()
      now.mockRestore()
    }
  })

  it('keeps its age when a reload saves the same data', async () => {
    const now = vi.spyOn(Date, 'now')
    try {
      now.mockReturnValue(1_000)
      await save(filledClient())
      const first = localStorage.getItem(CACHE_KEY)

      now.mockReturnValue(2_000)
      const options = persistOptions(createPersister(localStorage))
      const client = await restore(options)
      await persistQueryClientSave({ queryClient: client, ...options })

      expect(localStorage.getItem(CACHE_KEY)).toBe(first)
    } finally {
      now.mockRestore()
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
