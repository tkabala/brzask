# Agents (MCP)

brzask serves its tools for AI agents over the
[Model Context Protocol](https://modelcontextprotocol.io) at `/mcp`, on the
same port as the API. An agent can explain today's picks, look at what you
open and what you never do, propose or mute sources, edit interests and
start a dry run, with the same rules and the same change log as the web app.

## Connect

Create a token. A `read` token reads and starts dry runs; a `write` token may
also change sources, interests and the pause, and start real runs. A
`propose` token reads and starts dry runs like a read token, and its changes
[wait for your approval](#approving-changes).

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
| `start_replay` | read | Chooses the last days' digests again, as set up and without some sources, to check a mute before proposing it; follow it with `get_run` |
| `add_source` | write or propose | Finds a site's feed and proposes it (or adds it as active) |
| `set_source_status`, `rename_source`, `set_source_note` | write or propose | Read a source again, mute it, reject a pending one; rename; note why |
| `add_interest`, `edit_interest` | write or propose | Interests the ranking and discovery follow |
| `pause`, `resume` | write or propose | No digest until a given time |

Settings, API keys and tokens are out of reach. Nothing is deleted: a
source is muted or rejected, which keeps its articles and stops it from being
proposed again. A dry run writes nothing but still calls the paid model APIs,
a few cents for a digest, and a replay of 14 days about $0.10; runs and
replays count towards the [spending limits](configuration.md#spending-limits),
and a replay is refused once a limit is reached.

Every change is logged as `agent:<token name>` and can be undone like any
other ([Data model](data-model.md#change-log)):

```console
$ brzask config history --limit 20
$ brzask config rollback 214
```

## Approving changes

With a `propose` token an agent's change does not happen: it is checked as
if it would (a taken name or a missing feed is refused at once) and logged as
`proposed`. The tool answers with the change's ID, and `list_changes` later
shows whether it was applied or rejected. Proposals wait on the **Changes**
page of the web app, which shows each one with the values before and after and
the agent's reason, and counts them in the navigation. From the command line:

```console
$ brzask config history --status proposed
$ brzask config approve 215
$ brzask config reject 216
```

Approving applies the change exactly as the agent's write would have, as the
same entry in the log: its actor stays `agent:<token name>`, and it can be
rolled back like any other change. It is refused, with nothing written, when
what it changes was edited since it was proposed (`change 215 is out of date:
status is now 'muted', not 'active'`), or when the name or feed it adds was
taken meanwhile; reject it then, or let the agent propose it again.
Proposals do not expire.

Adding a source with `active` false is not a proposal: the source is added
as pending, as discovery adds them, and waits for you on the Sources page.

## Skills

The repository ships [skills](https://agentskills.io) for agents: written
procedures that tell an agent which tools to call, in what order, and what to
report.

| Skill | Ask for it with | Token |
|---|---|---|
| `weekly-tune-up` | "do the weekly tune-up" | `propose` |
| `empty-digest` | "why only 5 today?" | `read` |
| `onboarding` | "set up my interests" | `propose` or `write` |
| `explain-pick` | "why was this picked?" | `read` |

The **weekly tune-up** looks at what was shown and opened over the week and
the month, picks sources that were shown often and never opened (or have
been failing for a week), and checks them with `start_replay`: it proposes
a mute only when replaying the last 14 days without the source loses no
opened article. It may also suggest up to three new sites on the topics you
open. **Empty digest** walks today's digest run stage by stage (pause, pool,
ranking, deduplication, selection, spending limit) and names the one that
left the digest short. **Onboarding** asks what you want to read and drafts
the interests with you; nothing is saved before you agree. **Explain pick**
tells how an article got into the digest: how many it competed with, its
rank, what deduplication left and the interest it was picked for.

With Claude Code, add the repository as a plugin marketplace and install the
plugin:

```console
$ claude plugin marketplace add tkabala/brzask
$ claude plugin install brzask@brzask
```

Other agents read the same files: copy the folders under
[`skills/`](https://github.com/tkabala/brzask/tree/main/skills) into the
agent's skills directory. The skills need the MCP server added as above.

## Untrusted text

Feed entries and web pages are written by anyone, and the summaries and
reasons brzask stores were written by a model reading them. In every result
that text sits under an `external` key: titles, summaries, article text,
source names (most come from feed titles), source notes (pipelines quote
titles in them), run stats and change details. The
server tells agents to treat those values as data, never as instructions.
A page that says "mute every source" stays a page; still, prefer a `read`
token unless the agent needs to change things, and a `propose` token over a
`write` token when you want to see each change first.

## Behind a proxy

`/mcp` must reach brzask with the `Authorization` header intact. A proxy that
asks for its own login (basic auth, single sign-on) must let `/mcp` through,
as it does for [the feed](reverse-proxy.md#feed-readers-and-open-links):
the agent's token is the login. Under a path, the address is
`https://home.example/brzask/mcp`.
