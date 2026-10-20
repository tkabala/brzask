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

To add a decision, copy the [template](0000-template.md) to the next free number,
fill it in and add it to this table and to the `nav` in `mkdocs.yml`.
