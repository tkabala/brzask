import { ApiProblem, toApiProblem } from './api'

describe('toApiProblem', () => {
  it('keeps a problem body with its status and Retry-After', () => {
    const response = new Response(null, { status: 429, headers: { 'Retry-After': '60' } })
    const error = toApiProblem(
      { title: 'Too Many Requests', status: 429, detail: 'Later.' },
      response,
    )

    expect(error).toBeInstanceOf(ApiProblem)
    expect(error.message).toBe('Later.')
    expect((error as ApiProblem).retryAfter).toBe(60)
  })

  it('stands in for a body that is no problem', () => {
    const response = new Response(null, { status: 502, statusText: 'Bad Gateway' })
    const error = toApiProblem('<html>proxy error</html>', response) as ApiProblem

    expect(error.problem).toEqual({ title: 'Bad Gateway', status: 502 })
    expect(error.retryAfter).toBeNull()
  })

  it('passes on network errors', () => {
    const failure = new TypeError('Failed to fetch')

    expect(toApiProblem(failure, undefined)).toBe(failure)
  })
})
