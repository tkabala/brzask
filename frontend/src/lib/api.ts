import { client } from '@/client/client.gen'
import type { Problem } from '@/client/types.gen'

/** An error answer of the API: an RFC 9457 problem, or a stand-in when the body was none. */
export class ApiProblem extends Error {
  readonly status: number
  readonly problem: Problem
  /** Seconds from Retry-After, e.g. on a login lockout (429). */
  readonly retryAfter: number | null

  constructor(status: number, problem: Problem, retryAfter: number | null = null) {
    super(problem.detail ?? problem.title)
    this.name = 'ApiProblem'
    this.status = status
    this.problem = problem
    this.retryAfter = retryAfter
  }
}

function isProblem(body: unknown): body is Problem {
  return (
    typeof body === 'object' &&
    body !== null &&
    typeof (body as Partial<Problem>).title === 'string' &&
    typeof (body as Partial<Problem>).status === 'number'
  )
}

export function toApiProblem(body: unknown, response: Response | undefined): Error {
  if (response === undefined) {
    // No answer at all: the server is down or the network is.
    return body instanceof Error ? body : new Error(String(body))
  }
  const problem = isProblem(body)
    ? body
    : { title: response.statusText || `HTTP ${String(response.status)}`, status: response.status }
  const retryAfter = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
  return new ApiProblem(response.status, problem, Number.isNaN(retryAfter) ? null : retryAfter)
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

// The session's CSRF token, from the login answer or GET /auth/session. Held in
// memory only; the gate fetches the session again after a reload.
let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

let configured = false

/** Point the generated client at this server and attach CSRF tokens and problems. */
export function configureApi(baseUrl: string = window.location.origin): void {
  client.setConfig({ baseUrl, credentials: 'same-origin' })
  if (configured) return
  configured = true
  client.interceptors.request.use((request) => {
    if (csrfToken !== null && UNSAFE.has(request.method)) {
      request.headers.set('X-CSRF-Token', csrfToken)
    }
    return request
  })
  client.interceptors.error.use((error, response) => toApiProblem(error, response))
}
