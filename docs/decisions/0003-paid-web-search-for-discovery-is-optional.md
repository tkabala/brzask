---
status: accepted
date: 2026-10-20
---

# Paid web search for discovery is optional, and worth its cost

## Context and problem statement

Discovery finds new sources for the reader's interests: it searches the web,
resolves the results to feeds and lets an LLM judge enable, hold or reject
them. The search is the only part that needs a service of its own:
`WEB_SEARCH` takes an online LLM through the LLM API (`llm-online`, paid per
call), a self-hosted SearXNG instance, or the Brave Search API, and when it is
empty discovery does not run. Does brzask need paid search, and should it be
on by default?

## Decision drivers

- Sources added by discovery must stay and be read; otherwise discovery only
  adds noise for the source review to mute.
- The default setup works against any OpenAI-compatible endpoint, local ones
  included.
- The default deployment stays `migrate` + `api` + `worker` + `db`.
- Cost of a weekly run.

## Considered options

- `WEB_SEARCH` empty by default; `llm-online` recommended where the LLM API offers an online model.
- `WEB_SEARCH=llm-online` by default.
- SearXNG as the recommended search, shipped as an extra service.

## Decision outcome

Chosen option: empty by default, `llm-online` recommended, because discovery
with an online LLM search pays for itself in what the reader opens, but an
online model is not available on every endpoint brzask supports, and SearXNG
would add a service to the default deployment without measured results.

### Evidence

`brzask sources stats` over daily use, judging sources enabled at least 30 days
before 2026-10-20. Discovery in that period always searched with an online LLM
(`perplexity/sonar`); those rows predate recording the adapter, so the command
lists them as "not recorded". Opens are recorded from 2026-08-28 on.

| Origin | Enabled 30+ days ago | Still active | Shown in a digest | Opened | Opens |
|---|---|---|---|---|---|
| discovery (online LLM search) | 37 | 36 (97%) | 30 (81%) | 9 (24%) | 13 |
| manual | 108 | 44 (41%) | 40 (37%) | 8 (7%) | 23 |
| visited | 1 | 1 | 1 | 0 | 0 |

Discovered sources are 37 of the 146 judged sources and brought 13 of the 36
recorded opens. 64 of the 108 manual sources were muted, all of them added in
the first week, which lowers the manual shares.

A discovery run over 9 interests with `llm-online` (`perplexity/sonar`) cost
$0.052, almost all of it the search (a dry run of the same setup: $0.050 of
$0.053): about $2.70 a year at the default weekly schedule. It proposed 80
sites, resolved 43 feeds, judged 21 and enabled 13.

SearXNG and Brave have only been tested against recorded responses, never in
daily use, so there is nothing to compare them with yet.

### Consequences

- Good, because a new installation works with any endpoint, and discovery is
  one setting away (`WEB_SEARCH=llm-online` with OpenRouter).
- Good, because the cost of discovery is known and small.
- Bad, because an installation that keeps the defaults does not find new
  sources: one of brzask's core ideas is off until the reader turns it on.
  The setup documentation has to say so.

## Pros and cons of the options

### Empty by default, `llm-online` recommended

- Good, because nothing fails on endpoints without an online model.
- Bad, because discovery is off until configured.

### `llm-online` by default

- Good, because self-maintaining sources work out of the box on OpenRouter.
- Bad, because on a local or other endpoint without an online model every
  weekly run fails until the setting is changed.

### SearXNG recommended

- Good, because searching costs nothing per call and stays self-hosted.
- Bad, because it adds a service to run and maintain, and its results for
  discovery are unmeasured.

## More information

Run `brzask sources stats` again on 2026-11-19, when the 13 sources enabled by
the first run that recorded its adapter (`llm-online`) are 30 days old, and
after any run with SearXNG or Brave has had 30 days. Revisit this decision when
a free adapter has numbers.
