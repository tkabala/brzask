import { http, type HttpResponseResolver } from 'msw'

import type { DigestOut, SessionOut } from '@/client/types.gen'
import { problem as problemResponse } from '@/demo/handlers'

import { server } from './server'

type Handler = (request: Request) => Response | Promise<Response>

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

export function problem(status: number, title: string, detail?: string, headers = {}): Response {
  return problemResponse(status, title, detail, headers)
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

const METHODS = {
  GET: http.get,
  POST: http.post,
  PUT: http.put,
  PATCH: http.patch,
  DELETE: http.delete,
}

function matches(pattern: string, key: string): boolean {
  const want = pattern.split('/')
  const have = key.split('/')
  return (
    want.length === have.length && want.every((part, i) => part.startsWith(':') || part === have[i])
  )
}

/**
 * Overrides of the demo API for one test, by "METHOD /path" (`:name` matches
 * a segment); the rest is answered by the demo handlers. Records every request.
 */
export function fakeApi(handlers: Record<string, Handler>) {
  const requests: Request[] = []
  server.events.removeAllListeners('request:start')
  server.events.on('request:start', ({ request }) => {
    requests.push(request.clone())
  })
  server.use(
    ...Object.entries(handlers).map(([key, handle]) => {
      const [method, path] = key.split(' ') as [keyof typeof METHODS, string]
      const resolver: HttpResponseResolver = ({ request }) => handle(request)
      return METHODS[method](`*${path}`, resolver)
    }),
  )
  return {
    requests,
    /** The requests sent to "METHOD /path" (patterns allowed). */
    sent: (pattern: string) =>
      requests.filter((r) => matches(pattern, `${r.method} ${new URL(r.url).pathname}`)),
  }
}
