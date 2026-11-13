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
| `api_tokens` | Hashed API tokens with a `read`, `write` or `feed` scope |
| `login_sessions` | Browsers logged in with the password, by hash of their cookie; logging out deletes the row |

## Articles

An article moves through these steps:

```
fetched ──► seen ──► ranked (rank set) ──► shown (in a digest) ──► opened
              │                  │
              │                  └─► repeat (dropped as a repeat of a shown article)
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
- **`state = repeat`**: dropped by deduplication as a repeat of an article
  shown in the last days, under another link, or as a same-day duplicate of an
  article picked for that day's digest. Like a shown link, it is never a
  candidate again, so it cannot take a top slot day after day.
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

Two URLs are the same feed when they differ only in case that does not matter:
the scheme and host, and the path on GitHub and Reddit, where owners,
repositories and subreddits ignore case. Elsewhere a path's case counts.

Discovery also catches copies under another URL. A GitHub fork is replaced by
its parent repository, and a proposed feed whose recent items are mostly one
known source's articles, and also a good part of that source's newest ones (the
same blog under a second feed URL, a mirror of release notes), is stored as
`rejected` with a note naming that source. The second condition keeps a blog
from passing for a copy of an aggregator that links to its posts. GitHub
releases count as the same item when their tags match without a leading `v`.

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

Every pipeline run (`digest`, `review`, `visited`, `discovery`) writes one row,
and so does a replay an agent starts (`replay`, always a dry run), so that its
cost counts towards the spending limits. A replay run is not a pipeline:
nothing schedules it and the status page's pipelines leave it out.
A run an agent started over MCP has `started_by` set to `agent:<token name>`,
which `AGENT_RUNS_PER_DAY` counts; the scheduler and the CLI leave it empty.
Its `id` is the same as the `run_id` in the logs, so a failed run can be traced
from the status page to its log lines. `status` is `running`, `ok`, `skipped`
(paused, or today's digest already exists) or `failed`. A process stopped
outright cannot close its run; the next start of the API or the worker marks
such a row `failed` with the error `abandoned (the process running it
stopped)`, once the pipeline's lock shows nothing runs it.

## Change log

Changes are recorded with who made them (`actor`: `user` for the command
line and a password login, `user:<name>` behind a proxy, `token:<name>`,
`agent:<name>` through [MCP](agents.md), `pipeline:<kind>`), what changed (`action`,
`entity_type`, `entity_id`, `before`, `after`) and why (`reason`). A change
is `proposed` while it waits for approval, then `applied` or `rejected`;
an applied change can later be `reverted`. `decided_at` is when the status
last changed.

An agent with a `propose` token only proposes ([Approving
changes](agents.md#approving-changes)). Its proposal is logged with the
values the change would set and the ones it saw; an addition has no
`entity_id` yet. Approving turns that same row into `applied`, with what was
actually set and the new entity's ID, so one change stays one row. Approval
is refused while any field in `before` differs from the current value.

List changes, newest first, and undo one by its ID:

```bash
brzask config history --entity source:12
brzask config rollback 214 --reason "muted the wrong feed"
```

A rollback marks the original change `reverted` and records a change of its
own, named `<action>.rollback`, so the undo stays in the history. It is
refused, with nothing written, when a field the change set has changed since;
a later change to a different field does not block it. A rollback cannot be
rolled back: make the change again instead.

| Change | What a rollback does |
|---|---|
| Source muted, enabled, marked dead or rejected | Restores its status and note. Back to active also forgets past fetch failures, as enabling does. |
| Source renamed | Restores the name, unless it is taken now |
| Source note changed | Restores the earlier note |
| Source added | Mutes an active source and rejects a pending one |
| Interest added | Deactivates it, unless it was edited since |
| Interest edited | Restores the edited fields, unless the old topic is taken now |
| Digest paused | Restores the earlier pause if it is still ahead, otherwise ends the pause |
| Digest resumed | Restores the pause if it is still ahead |

An added source is muted or rejected rather than deleted: its articles point
to it, and keeping the URL known stops discovery from proposing it again.

These changes cannot be rolled back:

- A moved source: the feed's permanent redirect would move it again on the
  next fetch.
- A source created as rejected: there is nothing to undo, and
  `brzask sources enable` follows it.
- API tokens: use `brzask tokens`, so that a revoked credential does not come
  back with one command.
- An embedding model switch: it needs the digest lock and complete vectors,
  so it belongs to `brzask reembed`.

## Conventions

- Statuses are stored as text with a CHECK constraint rather than native
  Postgres enums, so adding a value is a one-statement migration.
- Constraint and index names follow a fixed pattern (`uq_articles_link`,
  `fk_articles_source_id_sources`, ...), so migrations can refer to them.
- All timestamps are `timestamptz`.
