/** Demo data for stories and tests: one plausible day of brzask. */
import type {
  ArticleOut,
  DigestDayOut,
  DigestOut,
  InterestOut,
  RankingOut,
  RunOut,
  SearchResults,
  SourceOut,
  StatusOut,
} from '@/client/types.gen'

export const DAY = '2026-10-21'

function article(id: number, fields: Partial<ArticleOut>): ArticleOut {
  return {
    id,
    link: `https://news.example/${String(id)}`,
    open_url: `/open?id=${String(id)}&sig=demo`,
    title: `Article ${String(id)}`,
    original_title: `Article ${String(id)}`,
    summary: null,
    why_it_matters: null,
    topic: null,
    source: { id: 1, name: 'Phoronix' },
    state: 'shown',
    published_at: `${DAY}T05:00:00Z`,
    first_seen_at: `${DAY}T06:00:00Z`,
    digest_date: DAY,
    position: id,
    shown_at: `${DAY}T07:00:00Z`,
    opened_at: null,
    ...fields,
  }
}

const postgres = article(1, {
  title: 'PostgreSQL 19 beta brings asynchronous I/O to every read',
  summary: 'The first beta makes asynchronous reads the default and adds skip scans.',
  why_it_matters: 'You run Postgres; the beta shows what to test before the upgrade.',
  topic: 'Postgres',
  source: { id: 2, name: 'PostgreSQL News' },
  opened_at: `${DAY}T08:12:00Z`,
})
const torvalds = article(2, {
  title: 'Linus Torvalds merges AI-written page cache work',
  summary: 'A patch series drafted with an AI agent landed in 7.3 after review.',
  why_it_matters: 'A real-world case of agent-written kernel code reaching mainline.',
  topic: 'AI agents',
})
const hermes = article(3, {
  title: 'Hermes Agent 0.4 adds tool sandboxes',
  summary: 'Each tool call now runs in its own sandbox with a time limit.',
  why_it_matters: 'Matches the notes: release notes with real changes, not webinars.',
  topic: 'Hermes Agent',
  source: { id: 3, name: 'github.com/hermes/agent' },
})

export const articles: ArticleOut[] = [postgres, torvalds, hermes]

export const digest: DigestOut = { date: DAY, articles }
export const emptyDigest: DigestOut = { date: DAY, articles: [] }

export const ranking: RankingOut = {
  article_id: 2,
  position: 2,
  topic: 'AI agents',
  why_it_matters: 'A real-world case of agent-written kernel code reaching mainline.',
  rank: 4,
  pool: 200,
  ranked: 40,
  top: 15,
  ranking_method: 'llm',
  deduplicated_to: 12,
  deduplication_method: 'judge',
  run_id: '0b6f4c1e-2f1a-4c55-9d43-6c9a4a1f2e10',
}

export const days: DigestDayOut[] = [
  { date: '2026-10-21', articles: 7, opened: 2 },
  { date: '2026-10-20', articles: 7, opened: 0 },
  { date: '2026-10-17', articles: 7, opened: 3 },
]

export const searchResults: SearchResults = {
  model: 'google/gemini-embedding-001',
  items: [
    { article: postgres, similarity: 0.82 },
    { article: torvalds, similarity: 0.61 },
  ],
}

function source(id: number, fields: Partial<SourceOut>): SourceOut {
  return {
    id,
    name: `Source ${String(id)}`,
    url: `https://source-${String(id)}.example/feed.xml`,
    site_url: `https://source-${String(id)}.example/`,
    kind: 'feed',
    status: 'active',
    origin: 'manual',
    origin_detail: null,
    note: null,
    created_at: '2026-09-01T10:00:00Z',
    health: {
      fetched_at: `${DAY}T07:00:00Z`,
      failing_since: null,
      permanent_failing_since: null,
      failed_at: null,
      fetch_failures: 0,
      fetch_error: null,
    },
    activity: { articles: 40, ranked: 6, shown: 3, opened: 1 },
    ...fields,
  }
}

const phoronix = source(1, { name: 'Phoronix' })

export const sources: SourceOut[] = [
  phoronix,
  source(2, {
    name: 'VentureBeat AI',
    health: {
      fetched_at: '2026-10-18T07:00:00Z',
      failing_since: '2026-10-19T07:00:00Z',
      permanent_failing_since: null,
      failed_at: `${DAY}T07:00:00Z`,
      fetch_failures: 3,
      fetch_error: 'HTTP 429 Too Many Requests',
    },
    activity: { articles: 12, ranked: 0, shown: 0, opened: 0 },
  }),
  source(3, { name: 'Old blog', status: 'muted', note: 'no article opened in 60 days' }),
]

export const pendingSources: SourceOut[] = [
  source(4, {
    name: "Maurice's Blog",
    status: 'pending',
    origin: 'visited',
    note: 'You opened "500B Tokens Later: Letting AI Agents Decompile a Game" through Hacker News.',
    health: { ...phoronix.health, fetched_at: null },
    activity: { articles: 0, ranked: 0, shown: 0, opened: 0 },
  }),
  source(5, {
    name: 'Victor Da Luz',
    status: 'pending',
    origin: 'discovery',
    origin_detail: 'llm-online',
    note: 'discovery judge: interest fit 2.4/3, substance 1.2/2',
    activity: { articles: 0, ranked: 0, shown: 0, opened: 0 },
  }),
]

export const interests: InterestOut[] = [
  {
    id: 1,
    topic: 'Postgres',
    keywords: ['PostgreSQL', 'pgvector'],
    notes: 'want: releases, performance work; skip: vendor webinars',
    active: true,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
  },
  {
    id: 2,
    topic: 'AI agents',
    keywords: ['agent', 'MCP'],
    notes: '',
    active: true,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
  },
  {
    id: 3,
    topic: 'Video streaming',
    keywords: [],
    notes: '',
    active: false,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-10-10T10:00:00Z',
  },
]

function run(id: string, fields: Partial<RunOut>): RunOut {
  return {
    id,
    kind: 'digest',
    status: 'ok',
    dry_run: false,
    started_at: `${DAY}T07:00:00Z`,
    finished_at: `${DAY}T07:03:12Z`,
    stats: { usage: { cost_usd: 0.0812 } },
    timings: {},
    error: null,
    ...fields,
  }
}

const digestRun = run('9d1c7a52-0000-4000-8000-000000000001', {})
const discoveryRun = run('9d1c7a52-0000-4000-8000-000000000002', {
  kind: 'discovery',
  started_at: '2026-10-20T08:00:00Z',
  finished_at: '2026-10-20T08:02:05Z',
  stats: { usage: { cost_usd: 0.0518 } },
})
const reviewRun = run('9d1c7a52-0000-4000-8000-000000000003', {
  kind: 'review',
  status: 'failed',
  started_at: '2026-10-20T07:30:00Z',
  finished_at: '2026-10-20T07:30:02Z',
  stats: {},
  error: 'database is locked by another review',
})

export const runs: RunOut[] = [digestRun, discoveryRun, reviewRun]

export const status: StatusOut = {
  articles: { total: 5345, shown: 802, opened: 36 },
  sources: { active: 95, pending: 2, rejected: 69, muted: 65, dead: 0 },
  last_digest: DAY,
  paused_until: null,
  last_runs: {
    digest: digestRun,
    review: reviewRun,
    visited: null,
    discovery: discoveryRun,
  },
  embedding_model: 'google/gemini-embedding-001',
  embeddings: { 'google/gemini-embedding-001': 1072 },
}
