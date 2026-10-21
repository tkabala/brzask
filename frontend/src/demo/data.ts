/**
 * Demo data for stories and tests: the same invented instance `brzask
 * seed-demo` writes to a database, as of DAY. The instance comes from
 * instance.gen.json (`just demo-json`); this file shapes it like the API.
 */
import type {
  ArticleOut,
  DigestDayOut,
  DigestOut,
  InterestOut,
  RankingOut,
  RunKind,
  RunOut,
  SearchResults,
  SourceOut,
  SourceStatus,
  StatusOut,
} from '@/client/types.gen'

import instance from './instance.gen.json'

export const DAY = instance.day

function must<T>(item: T | undefined, what: string): T {
  if (item === undefined) throw new Error(`the demo instance has no ${what}`)
  return item
}

const sourceNames = new Map(instance.sources.map((s) => [s.id, s.name]))

/** Every stored article, oldest first. */
export const allArticles: ArticleOut[] = instance.articles.map((a) => ({
  id: a.id,
  link: a.link,
  open_url: `/open?id=${String(a.id)}&sig=demo`,
  title: a.title,
  original_title: a.title,
  summary: a.summary,
  why_it_matters: a.why_it_matters,
  topic: a.topic,
  source: { id: a.source_id, name: sourceNames.get(a.source_id) ?? '' },
  state: a.position === null ? 'seen' : 'shown',
  published_at: a.published_at,
  first_seen_at: a.first_seen_at,
  digest_date: a.digest_date,
  position: a.position,
  shown_at: a.shown_at,
  opened_at: a.opened_at,
}))

/** The digest of `day`, empty when there was none. */
export function digestOf(day: string): DigestOut {
  return {
    date: day,
    articles: allArticles
      .filter((a) => a.digest_date === day)
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0)),
  }
}

export const digest = digestOf(DAY)
export const articles = digest.articles
export const emptyDigest: DigestOut = { date: DAY, articles: [] }

export const days: DigestDayOut[] = [
  ...new Set(allArticles.flatMap((a) => (a.digest_date ? [a.digest_date] : []))),
]
  .sort()
  .reverse()
  .map((date) => {
    const shown = digestOf(date).articles
    return { date, articles: shown.length, opened: shown.filter((a) => a.opened_at).length }
  })

export const runs: RunOut[] = instance.runs.map((r) => ({
  id: r.id,
  kind: r.kind as RunKind,
  status: r.status as RunOut['status'],
  dry_run: false,
  started_at: r.started_at,
  finished_at: r.finished_at,
  stats: r.stats,
  timings: {},
  error: r.error,
}))

function latestRun(kind: RunKind): RunOut | null {
  return runs.find((r) => r.kind === kind) ?? null
}

/** How the article at `position` of today's digest got there. */
export function rankingOf(article: ArticleOut): RankingOut {
  const run = runs.find((r) => r.kind === 'digest' && r.started_at === article.shown_at)
  const stats = (run?.stats ?? {}) as {
    pool?: { candidates: number }
    ranking?: { method: string; ranked: number; top: number }
    deduplication?: { same_day_method: string; survivors: number }
  }
  return {
    article_id: article.id,
    position: article.position,
    topic: article.topic,
    why_it_matters: article.why_it_matters,
    rank: instance.articles.find((a) => a.id === article.id)?.rank ?? null,
    pool: stats.pool?.candidates ?? null,
    ranked: stats.ranking?.ranked ?? null,
    top: stats.ranking?.top ?? null,
    ranking_method: stats.ranking?.method ?? null,
    deduplicated_to: stats.deduplication?.survivors ?? null,
    deduplication_method: stats.deduplication?.same_day_method ?? null,
    run_id: run?.id ?? null,
  }
}

export const ranking = rankingOf(must(articles[1], 'second article today'))

const EMBEDDING_MODEL = 'google/gemini-embedding-001'

export const searchResults: SearchResults = {
  model: EMBEDDING_MODEL,
  items: articles.slice(0, 2).map((article, n) => ({ article, similarity: 0.82 - n * 0.2 })),
}

const allSources: SourceOut[] = instance.sources.map((s) => {
  const published = instance.articles.filter((a) => a.source_id === s.id)
  return {
    id: s.id,
    name: s.name,
    url: s.url,
    site_url: s.site_url,
    kind: 'feed',
    status: s.status as SourceStatus,
    origin: s.origin as SourceOut['origin'],
    origin_detail: s.origin_detail,
    note: s.note,
    created_at: s.created_at,
    health: s.health,
    activity: {
      articles: published.length,
      ranked: published.length, // every stored demo article made the top of a ranking
      shown: published.filter((a) => a.position !== null).length,
      opened: published.filter((a) => a.opened_at !== null).length,
    },
  }
})

export const sources = allSources.filter((s) => s.status !== 'pending')
export const pendingSources = allSources.filter((s) => s.status === 'pending')

/** A healthy source to copy, e.g. for one added in a story. */
export const healthySource: SourceOut = must(sources[0], 'active source')

export const interests: InterestOut[] = instance.interests.map((i) => ({
  ...i,
  created_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
}))

const shown = allArticles.filter((a) => a.position !== null)

export const status: StatusOut = {
  articles: {
    total: allArticles.length,
    shown: shown.length,
    opened: shown.filter((a) => a.opened_at).length,
  },
  sources: Object.fromEntries(
    (['active', 'pending', 'rejected', 'muted', 'dead'] as const).map((state) => [
      state,
      allSources.filter((s) => s.status === state).length,
    ]),
  ),
  last_digest: DAY,
  paused_until: null,
  last_runs: {
    digest: latestRun('digest'),
    review: latestRun('review'),
    visited: latestRun('visited'),
    discovery: latestRun('discovery'),
  },
  embedding_model: EMBEDDING_MODEL,
  embeddings: { [EMBEDDING_MODEL]: allArticles.length },
}
