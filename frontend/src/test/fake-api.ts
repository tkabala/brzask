import { vi } from 'vitest'

import type { DigestOut, Problem, SessionOut } from '@/client/types.gen'

type Handler = (request: Request) => Response | Promise<Response>

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

export function problem(status: number, title: string, detail?: string, headers = {}): Response {
  const body: Problem = { type: 'about:blank', title, status, ...(detail ? { detail } : {}) }
  return json(body, status, { 'Content-Type': 'application/problem+json', ...headers })
}

export const loggedOut: SessionOut = {
  mode: 'password',
  authenticated: false,
  user: null,
  csrf_token: null,
}

export const loggedIn: SessionOut = {
  mode: 'password',
  authenticated: true,
  user: null,
  csrf_token: 'csrf-1',
  expires_at: '2026-11-20T09:00:00Z',
}

export const emptyDigest: DigestOut = { date: '2026-10-21', articles: [] }

function matches(pattern: string, key: string): boolean {
  const want = pattern.split('/')
  const have = key.split('/')
  return (
    want.length === have.length && want.every((part, i) => part.startsWith(':') || part === have[i])
  )
}

/** A fake API on `fetch`: handlers by "METHOD /path", where `:name` matches any
 * one segment and an exact path wins; records every request. */
export function fakeApi(handlers: Record<string, Handler>) {
  const requests: Request[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init)
      requests.push(request.clone())
      const key = `${request.method} ${new URL(request.url).pathname}`
      const handler =
        handlers[key] ?? Object.entries(handlers).find(([pattern]) => matches(pattern, key))?.[1]
      return handler ? handler(request) : problem(404, 'Not Found', `no fake for ${key}`)
    }),
  )
  return {
    requests,
    /** The requests sent to "METHOD /path" (patterns allowed). */
    sent: (pattern: string) =>
      requests.filter((r) => matches(pattern, `${r.method} ${new URL(r.url).pathname}`)),
  }
}
