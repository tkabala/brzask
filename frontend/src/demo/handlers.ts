/**
 * The API on demo data, for Storybook (in the browser) and tests (in Node).
 *
 * Hand-written to answer like the server: the same paths, cursor pages and
 * problem details. Changes (approving a source, pausing) live in memory until
 * `resetDemo()`, which every story and test starts with.
 */
import { http, HttpResponse, type RequestHandler } from 'msw'

import type {
  ArticleOut,
  InterestChange,
  InterestOut,
  NewInterest,
  NewPause,
  NewSource,
  Problem,
  SessionOut,
  SourceChange,
  SourceOut,
} from '@/client/types.gen'

import * as demo from './data'

/** The password the demo login accepts. */
export const DEMO_PASSWORD = 'demo'

const API = '*/api/v1'

export const loggedInSession: SessionOut = {
  mode: 'password',
  authenticated: true,
  user: null,
  csrf_token: 'demo-csrf',
  expires_at: '2026-11-20T09:00:00Z',
}

export const loggedOutSession: SessionOut = {
  mode: 'password',
  authenticated: false,
  user: null,
  csrf_token: null,
}

function fresh() {
  return structuredClone({
    session: loggedInSession,
    articles: demo.allArticles,
    digest: demo.digest,
    days: demo.days,
    sources: [...demo.pendingSources, ...demo.sources],
    interests: demo.interests,
    runs: demo.runs,
    status: demo.status,
  })
}

let db = fresh()

/** Back to the demo data as written, logged in. */
export function resetDemo(): void {
  db = fresh()
}

/** Start logged out (e.g. a login story); the demo password logs in. */
export function logOutDemo(): void {
  db.session = structuredClone(loggedOutSession)
}

export function problem(status: number, title: string, detail?: string, headers = {}) {
  const body: Problem = { type: 'about:blank', title, status, ...(detail ? { detail } : {}) }
  return HttpResponse.json(body, {
    status,
    headers: { 'Content-Type': 'application/problem+json', ...headers },
  })
}

/** One cursor page of `items`; the cursor is the next index, as the client never reads it. */
function page(items: readonly unknown[], url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? 50)
  const start = Number(url.searchParams.get('cursor') ?? 0)
  const next = start + limit
  return HttpResponse.json({
    items: items.slice(start, next),
    next_cursor: next < items.length ? String(next) : null,
  })
}

function allArticles(): ArticleOut[] {
  return db.articles
}

const authenticated = () => db.session.authenticated

export const handlers = [
  // --- Auth -----------------------------------------------------------------
  http.get(`${API}/auth/session`, () => HttpResponse.json(db.session)),
  http.post(`${API}/auth/login`, async ({ request }) => {
    const { password } = (await request.json()) as { password: string }
    if (password !== DEMO_PASSWORD) return problem(401, 'Unauthorized', 'Wrong password.')
    db.session = structuredClone(loggedInSession)
    return HttpResponse.json(db.session)
  }),
  http.post(`${API}/auth/logout`, () => {
    db.session = structuredClone(loggedOutSession)
    return new HttpResponse(null, { status: 204 })
  }),

  // Everything below needs a session, as on the server.
  http.all(`${API}/*`, ({ request }) =>
    authenticated() || new URL(request.url).pathname.endsWith('/openapi.json')
      ? undefined
      : problem(401, 'Unauthorized', 'Log in first.'),
  ),

  // --- Digests and articles ---------------------------------------------------
  http.get(`${API}/digests/today`, () => HttpResponse.json(db.digest)),
  http.get(`${API}/digests`, ({ request }) => page(db.days, new URL(request.url))),
  http.get(`${API}/digests/:day`, ({ params }) =>
    HttpResponse.json(
      params.day === db.digest.date ? db.digest : demo.digestOf(String(params.day)),
    ),
  ),
  http.get(`${API}/articles/:id/ranking`, ({ params }) => {
    const article = allArticles().find((a) => String(a.id) === params.id)
    if (!article) return problem(404, 'Not Found', `no article ${String(params.id)}`)
    return HttpResponse.json(demo.rankingOf(article))
  }),
  http.get(`${API}/articles/:id`, ({ params }) => {
    const article = allArticles().find((a) => String(a.id) === params.id)
    return article
      ? HttpResponse.json(article)
      : problem(404, 'Not Found', `no article ${String(params.id)}`)
  }),
  http.get(`${API}/search`, ({ request }) => {
    const q = (new URL(request.url).searchParams.get('q') ?? '').trim().toLowerCase()
    if (!q) return problem(400, 'Bad Request', 'the search query must not be empty')
    // A stand-in for meaning: articles sharing a word with the query come first.
    const words = q.split(/\s+/)
    const items = allArticles()
      .map((article) => {
        const text = `${article.title} ${article.summary ?? ''}`.toLowerCase()
        const shared = words.filter((word) => text.includes(word)).length
        return { article, similarity: 0.45 + 0.4 * (shared / words.length) }
      })
      .sort((a, b) => b.similarity - a.similarity)
    return HttpResponse.json({ model: demo.searchResults.model, items })
  }),

  // --- Sources ----------------------------------------------------------------
  http.get(`${API}/sources`, ({ request }) => {
    const url = new URL(request.url)
    const statuses = url.searchParams.getAll('status')
    const items = db.sources
      .filter((s) => statuses.length === 0 || statuses.includes(s.status))
      .sort((a, b) => a.name.localeCompare(b.name))
    return page(items, url)
  }),
  http.post(`${API}/sources`, async ({ request }) => {
    const body = (await request.json()) as NewSource
    if (!body.url.includes('.')) {
      return problem(404, 'Not Found', `no RSS or Atom feed found for ${body.url}`)
    }
    const url = body.url.startsWith('http') ? body.url : `https://${body.url}`
    if (db.sources.some((s) => s.url === url)) {
      return problem(409, 'Conflict', `${url} is already a source`)
    }
    const added: SourceOut = {
      ...structuredClone(demo.healthySource),
      id: Math.max(...db.sources.map((s) => s.id)) + 1,
      name: body.name ?? new URL(url).hostname,
      url,
      site_url: url,
      health: { ...demo.healthySource.health, fetched_at: null },
      activity: { articles: 0, ranked: 0, shown: 0, opened: 0 },
    }
    db.sources.push(added)
    return HttpResponse.json(added, { status: 201 })
  }),
  http.get(`${API}/sources/:id`, ({ params }) => {
    const source = db.sources.find((s) => String(s.id) === params.id)
    return source
      ? HttpResponse.json(source)
      : problem(404, 'Not Found', `no source ${String(params.id)}`)
  }),
  http.patch(`${API}/sources/:id`, async ({ params, request }) => {
    const source = db.sources.find((s) => String(s.id) === params.id)
    if (!source) return problem(404, 'Not Found', `no source ${String(params.id)}`)
    const change = (await request.json()) as SourceChange
    if (change.name) source.name = change.name.trim()
    if (change.status) source.status = change.status
    return HttpResponse.json(source)
  }),

  // --- Interests --------------------------------------------------------------
  http.get(`${API}/interests`, () => HttpResponse.json(db.interests)),
  http.post(`${API}/interests`, async ({ request }) => {
    const body = (await request.json()) as NewInterest
    const topic = body.topic.trim()
    if (db.interests.some((i) => i.topic.toLowerCase() === topic.toLowerCase())) {
      return problem(409, 'Conflict', `interest '${topic}' already exists`)
    }
    const now = new Date().toISOString()
    const added: InterestOut = {
      id: Math.max(0, ...db.interests.map((i) => i.id)) + 1,
      topic,
      keywords: body.keywords ?? [],
      notes: body.notes ?? '',
      active: true,
      created_at: now,
      updated_at: now,
    }
    db.interests.push(added)
    return HttpResponse.json(added, { status: 201 })
  }),
  http.get(`${API}/interests/:id`, ({ params }) => {
    const interest = db.interests.find((i) => String(i.id) === params.id)
    return interest
      ? HttpResponse.json(interest)
      : problem(404, 'Not Found', `no interest '${String(params.id)}'`)
  }),
  http.patch(`${API}/interests/:id`, async ({ params, request }) => {
    const interest = db.interests.find((i) => String(i.id) === params.id)
    if (!interest) return problem(404, 'Not Found', `no interest '${String(params.id)}'`)
    const change = (await request.json()) as InterestChange
    Object.assign(
      interest,
      Object.fromEntries(Object.entries(change).filter(([, value]) => value !== null)),
      { updated_at: new Date().toISOString() },
    )
    return HttpResponse.json(interest)
  }),

  // --- Runs, status, pause ------------------------------------------------------
  http.get(`${API}/runs`, ({ request }) => page(db.runs, new URL(request.url))),
  http.get(`${API}/runs/:id`, ({ params }) => {
    const run = db.runs.find((r) => r.id === params.id)
    return run ? HttpResponse.json(run) : problem(404, 'Not Found', `no run ${String(params.id)}`)
  }),
  http.get(`${API}/status`, () => HttpResponse.json(db.status)),
  http.get(`${API}/pause`, () => HttpResponse.json({ until: db.status.paused_until })),
  http.put(`${API}/pause`, async ({ request }) => {
    const { until } = (await request.json()) as NewPause
    if (Date.parse(until) <= Date.now()) {
      return problem(400, 'Bad Request', `${until} is not in the future`)
    }
    db.status.paused_until = until
    return HttpResponse.json({ until })
  }),
  http.delete(`${API}/pause`, () => {
    db.status.paused_until = null
    return new HttpResponse(null, { status: 204 })
  }),
]

/**
 * Storybook parameters for the demo API with `overrides` answering first.
 * (Handler groups are tried in the order they are declared, the global one first.)
 */
export function withApi(...overrides: RequestHandler[]) {
  return { msw: { handlers: { api: [...overrides, ...handlers] } } }
}
