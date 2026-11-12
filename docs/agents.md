# Agents (MCP)

brzask serves its tools for AI agents over the
[Model Context Protocol](https://modelcontextprotocol.io) at `/mcp`, on the
same port as the API. An agent can explain today's picks, look at what you
open and what you never do, propose or mute sources, edit interests and
start a dry run, with the same rules and the same change log as the web app.

## Connect

Create a token. A `read` token reads and starts dry runs; a `write` token may
also change sources, interests and the pause, and start real runs.

```console
$ docker compose exec api brzask tokens create claude --scope read
brz_...
```

Then add the server to the agent. With Claude Code:

```console
$ claude mcp add --transport http brzask https://news.example.com/mcp \
    --header "Authorization: Bearer brz_..."
```

Any MCP client that speaks Streamable HTTP and can send a header works the
same way. The server is stateless and answers in JSON: every call is a
request of its own, authenticated by its token, so `brzask tokens revoke
claude` stops the agent on its next call.

With `AUTH_MODE=none` no token is needed and every call may write: use that
only on a machine nobody else can reach.

## Tools

| Tool | Token | What it does |
|---|---|---|
| `get_digest`, `list_digest_days` | read | A day's 7 in order, which were opened; the days with a digest |
| `get_article` | read | One article with its stored text (cut at 8,000 characters) |
| `explain_ranking` | read | How an article reached its place: pool, rank, methods |
| `search_articles` | read | Articles closest in meaning to a question (one embedding call) |
| `list_sources`, `get_source` | read | Status, note, fetch health and the last 30 days of each source |
| `source_survival` | read | Per origin and search adapter, how many sources stayed and were read |
| `open_stats` | read | Shown and opened articles over the last days, by source and by topic |
| `dedup_decisions` | read | What deduplication dropped in a digest run, with the judge's probability for grey-zone pairs |
| `costs` | read | Spending today and this month against the budget, cost of recent runs |
| `list_runs`, `get_run` | read | Pipeline runs and what each did |
| `list_interests`, `get_status`, `list_changes` | read | Interests, counts and last runs, the change log |
| `start_run` | read for a dry run, write otherwise | Starts a pipeline in the background; follow it with `get_run` |
| `add_source` | write | Finds a site's feed and proposes it (or adds it as active) |
| `set_source_status`, `rename_source`, `set_source_note` | write | Read a source again, mute it, reject a pending one; rename; note why |
| `add_interest`, `edit_interest` | write | Interests the ranking and discovery follow |
| `pause`, `resume` | write | No digest until a given time |

Settings, API keys and tokens are out of reach. Nothing is deleted: a
source is muted or rejected, which keeps its articles and stops it from being
proposed again. A dry run writes nothing but still calls the paid model APIs,
a few cents for a digest; runs count towards the
[spending limits](configuration.md#spending-limits).

Every change is logged as `agent:<token name>` and can be undone like any
other ([Data model](data-model.md#change-log)):

```console
$ brzask config history --limit 20
$ brzask config rollback 214
```

## Untrusted text

Feed entries and web pages are written by anyone, and the summaries and
reasons brzask stores were written by a model reading them. In every result
that text sits under an `external` key: titles, summaries, article text,
source names (most come from feed titles), run stats and change details. The
server tells agents to treat those values as data, never as instructions.
A page that says "mute every source" stays a page; still, prefer a `read`
token unless the agent needs to change things.

## Behind a proxy

`/mcp` must reach brzask with the `Authorization` header intact. A proxy that
asks for its own login (basic auth, single sign-on) must let `/mcp` through,
as it does for [the feed](reverse-proxy.md#feed-readers-and-open-links):
the agent's token is the login. Under a path, the address is
`https://home.example/brzask/mcp`.
