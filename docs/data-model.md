# Data model

brzask keeps everything in one Postgres database with the pgvector extension.
The tables are defined in `backend/src/brzask/db/models.py`; this page explains
what the states mean and why some columns exist.

## Tables

| Table | Holds |
|---|---|
| `sources` | RSS/Atom feeds, whether they are fetched, and where they came from |
| `interests` | Topics you care about: keywords and free-text reader notes |
| `articles` | Every fetched entry, its ranking, embedding, digest text and whether you opened it |
| `runs` | One row per pipeline run: status, stats, timings, error |
| `settings` | Values changed at runtime, such as a pause (configuration lives in environment variables) |
| `change_log` | Every change to sources, interests or configuration, by a person, a pipeline or an agent |
| `api_tokens` | Hashed API tokens with a `read` or `write` scope |

## Articles

An article moves through these steps:

```
fetched ──► seen ──► ranked (rank set) ──► shown (in a digest) ──► opened
              │
              └─► carried over to the next days, until it is too old
```

- **`state = seen`**: fetched and stored. Unshown articles from the last days
  are carried over into the next day's candidate pool.
- **`rank`**: the article's position in the LLM ranking. Only the top
  candidates get one, so `rank IS NOT NULL` means "made the top of the ranking".
- **`state = shown`**: picked for a digest. `digest_date` and
  `digest_position` say where it appeared; a constraint keeps both set or both
  empty, and only shown articles can have them. A row records one appearance,
  so a link is shown at most once: a shown link that turns up in a feed again
  is never a candidate.
- **`opened_at`**: the first time you opened the article. Opening is the only
  preference signal brzask uses, so this column drives learning, source review
  and measurement.

`digest_title`, `summary`, `why_it_matters` and `topic` are written in the
digest language when the article is picked.

### Embeddings

Vectors live in `article_embeddings`, one row per article and embedding model.
Every vector has 768 dimensions: every model is asked for vectors of that
size, so the column type never changes when the model does. Similarity queries
always name a model, so vectors of different models are never compared.

The digest embeds with one model, the active one: `EMBEDDING_MODEL` until
`brzask reembed` moves to another model, then the one recorded in `settings`.
`reembed` embeds every embedded article's `extracted_text` (the text that was
embedded) with the new model and switches only once all of them have a vector,
so the switch never leaves deduplication with a partial history. Vectors of
earlier models stay, so switching back costs nothing.
`extracted_text` holds the first 4000 characters, the text that was embedded;
rows holding only 2000 characters are embedded again from those, so their new
vectors come from a shorter input than the rest of the history.

## Sources

| Status | Meaning |
|---|---|
| `active` | Fetched every day |
| `pending` | Proposed (by discovery, an opened link or an OPML import), waiting for a decision |
| `rejected` | Declined; the row stays so the same URL is not proposed again |
| `muted` | Switched off, by hand or by the source review |
| `dead` | The feed no longer works |

`kind` is `release` for release-note feeds, which are judged on their content
instead of being dropped as noise. `origin` (`manual`, `discovery`, `visited`,
`opml`) and `origin_detail` record where a source came from, so it is possible
to measure which ways of finding sources produce feeds you keep reading.
Source names are unique ignoring case, so a name typed in any case finds
exactly one source.

### Fetch health

Every digest run records how each active source's fetch went:

| Column | Meaning |
|---|---|
| `fetched_at` | Last successful fetch, including "not modified" (HTTP 304) |
| `failing_since` | First failure of the current run of failures; empty while fetches succeed |
| `permanent_failing_since` | First failure of the current run of permanent errors (404, 410, 403, not a feed); empty when the last error was temporary (429, 5xx, timeout, network error, a 404 from YouTube's feed endpoint) |
| `failed_at` | Last failed fetch; empty while fetches succeed |
| `fetch_failures` | Failed fetches in a row |
| `fetch_error` | Error of the last failed fetch |

A successful fetch clears the failure columns. Temporary errors are told apart
from permanent ones because rate limits and outages go away by themselves,
while a feed answering 404 for weeks has moved or ended.
YouTube's feed endpoint is the exception: during its outages it answers 404
for every channel, so its 404 counts as temporary. `etag` and
`last_modified` are saved from each successful fetch and sent back on the next
one, so unchanged feeds answer 304.

### Why statistics join on `source_id`

Each article points to its source with a foreign key. Per-source statistics
(articles fetched, ranked, shown, opened) are grouped by `source_id`, not by
name: a source can be renamed without losing its history, two sources with
similar names are never merged, and an article keeps its numbers even if its
source's title changes in the feed. Deleting a source sets `source_id` to null
instead of deleting its articles, so digest history and opens are kept.

## Runs

Every pipeline run (`digest`, `review`, `visited`, `discovery`) writes one row.
Its `id` is the same as the `run_id` in the logs, so a failed run can be traced
from the status page to its log lines. `status` is `running`, `ok`, `skipped`
(paused, or today's digest already exists) or `failed`.

## Change log

Changes are recorded with who made them (`actor`), what changed (`action`,
`entity_type`, `entity_id`, `before`, `after`) and why (`reason`). A change
is `proposed` while it waits for approval, then `applied` or `rejected`;
an applied change can later be `reverted`.

## Conventions

- Statuses are stored as text with a CHECK constraint rather than native
  Postgres enums, so adding a value is a one-statement migration.
- Constraint and index names follow a fixed pattern (`uq_articles_link`,
  `fk_articles_source_id_sources`, ...), so migrations can refer to them.
- All timestamps are `timestamptz`.
