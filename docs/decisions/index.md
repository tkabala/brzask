# Architecture decisions

Significant decisions are recorded as Architecture Decision Records (ADRs) in the
[MADR](https://adr.github.io/madr/) format, one file per decision.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-trafilatura-as-the-default-page-extractor.md) | Trafilatura as the default page extractor | Accepted |
| [0003](0003-paid-web-search-for-discovery-is-optional.md) | Paid web search for discovery is optional | Accepted |
| [0004](0004-no-vector-index-until-history-needs-one.md) | No vector index until the history needs one | Accepted |
| [0005](0005-system-one-judgements-over-one-http-client.md) | System One judgements over one HTTP client for every model | Accepted |
| [0006](0006-llm-ranking-stays-the-default-over-composite-scores.md) | LLM ranking stays the default; composite scores are opt-in | Accepted |
| [0007](0007-a-judge-decides-same-day-duplicates-in-the-grey-zone.md) | A judge decides same-day duplicates in the grey zone | Accepted |
| [0008](0008-jev-stays-the-default-judge.md) | Jev stays the default judge | Accepted |
| [0009](0009-hand-set-composite-weights-until-opens-can-train-them.md) | Hand-set composite weights until opens can train them | Accepted |
| [0010](0010-rank-candidates-and-show-a-fixed-seven.md) | Rank candidates against each other and show a fixed 7 | Accepted |
| [0011](0011-opens-are-the-only-preference-signal.md) | Opening an article is the only preference signal | Accepted |
| [0012](0012-embedding-deduplication-across-days-and-within-the-day.md) | Embedding deduplication: a fixed threshold across days, an adaptive one within the day | Accepted |
| [0013](0013-reader-notes-outrank-keywords.md) | Reader notes outrank keywords | Accepted |
| [0014](0014-sources-maintain-themselves.md) | Sources maintain themselves: review, visited sites and discovery | Accepted |
| [0015](0015-release-notes-are-judged-by-what-they-change.md) | Release notes are judged by what they change | Accepted |
| [0016](0016-the-pool-takes-sources-in-turns.md) | The candidate pool takes sources in turns | Accepted |
| [0017](0017-measure-changes-by-replaying-past-days.md) | Measure changes by replaying past days | Accepted |
| [0018](0018-fastapi-with-a-generated-typed-client.md) | FastAPI, with the frontend client generated from its OpenAPI schema | Accepted |
| [0019](0019-typed-sqlalchemy-and-raw-sql-only-where-needed.md) | Typed SQLAlchemy for data access; raw SQL only for vector and ranking queries | Accepted |
| [0020](0020-one-worker-process-with-a-scheduler-and-no-queue.md) | One worker process with a scheduler, no task queue | Accepted |
| [0021](0021-one-image-for-every-command.md) | One image for every command, serving the web app itself | Accepted |
| [0022](0022-one-embedding-model-at-a-time-with-thresholds-per-model.md) | One embedding model at a time, 768 dimensions, thresholds per model | Accepted |

To add a decision, copy the [template](0000-template.md) to the next free number,
fill it in and add it to this table and to the `nav` in `mkdocs.yml`.
