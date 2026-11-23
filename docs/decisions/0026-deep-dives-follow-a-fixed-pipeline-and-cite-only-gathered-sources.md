---
status: accepted
date: 2026-11-23
---

# Deep dives follow a fixed pipeline and cite only gathered sources

## Context and problem statement

From an article's brief the reader can ask for a deep dive: a report with the
background that led to the article, steps to try in practice, and further
reading, written in the background and kept with the article. It is written
from text anyone can publish: the article, pages a web search returns, and
earlier articles in the archive. How much freedom should the model get to
find and use that text, and what may the report contain?

## Decision drivers

- Third-party text is data ([ADR 0023](0023-third-party-text-is-data-and-its-reach-is-bounded.md)):
  it must not choose what brzask does next, and what it can reach stays bounded.
- A report the reader acts on must say where each claim comes from, and must
  not carry links nobody gathered.
- Cost and time per report stay small and predictable, within the spending limits.
- Web search stays optional ([ADR 0003](0003-paid-web-search-for-discovery-is-optional.md)).

## Considered options

- An agent loop with search and fetch tools, running until the model is done
- A fixed pipeline: plan, gather, read, write, with two LLM calls
- No web at all: the article and the archive only

## Decision outcome

Chosen option: "a fixed pipeline", because it gives the model no tools: text
read along the way cannot start another search, fetch another page or end
the run early, and the number of calls, pages and characters is known before
the run starts.

1. **Plan** (one call): up to 3 background, 3 practical and 2 archive search
   queries; an unusable answer falls back to the article's title.
2. **Gather**: archive articles by meaning (by text only when nothing matches
   by meaning), at most 3; web results of each query in turn, the article
   itself and repeats removed, non-http(s) links dropped.
3. **Read**: the first 8 web results through the extractor chain, so every
   fetch keeps the address guard, robots rules and `FETCH_PROXY`; pages that
   cannot be read are dropped, each source is cut at 12,000 characters.
4. **Write** (one call): the report as JSON, every source inside
   `<untrusted>` marks and named by its number.

Structural bounds on what the model writes:

- Sources are cited by number only. A number not in the list is removed; a
  further-reading entry pointing at an unknown source or at the article itself
  is dropped. Every link a report shows is one of its gathered sources.
- The report is stored and served as structure and shown as text; no
  model-written HTML or Markdown is interpreted. The Markdown export escapes
  model and source text and percent-encodes link targets.
- A command is shown in a code block next to the number of the source it came
  from, and nothing runs it.
- Deep dives are written one at a time in the API process, checked against
  the spending limits when asked for and again when they start.

### Evidence

Five real dives on a copy of the production database (2026-11-23): a release,
a long essay, a video read from its transcript, a Polish personal finance
article with a focus line, and a tool announcement with web search through an
online model. Each took 45-94 seconds and cost $0.035-0.046, of which about
$0.032 (six searches) is the web search and $0.002-0.007 the two writing
calls. Every dive found 23-29 web results and read 8 pages; at least 4 of the
8 were cited in every report.

A separate review checked cited claims against the live pages. Most specific
facts (versions, flags, limits, prices) held. What did not: claims connecting
the article to the reader's interests that no source made, a command copied
from a page about a different engine, a commenter's remark stated as fact
with an invented reason, and archive sources that were rarely relevant (4 of
25 cited). The prompts now forbid each of these, and the archive keeps 3
sources found by meaning; in a second run 5 of 15 archive sources were cited.

### Consequences

- Good, because nothing a page says can make brzask fetch, search or call
  anything beyond the fixed plan, and every link in a report was gathered.
- Good, because cost and duration are bounded: two LLM calls, six searches,
  eight page reads.
- Bad, because the model cannot follow up on what it reads; a second search
  round would need a new decision.
- Bad, because a hostile page can still get a harmful command quoted in a
  report, attributed to that page by number; the reader decides whether to
  run it.
- Bad, because the sources can be one-sided when the search returns only one
  side; the report says what its sources say, not what is true.

## Pros and cons of the options

### An agent loop with tools

- Good, because it could search again when the first results are thin.
- Bad, because text it reads chooses its next action, and cost and duration
  have no fixed bound.

### No web at all

- Good, because nothing outside brzask is fetched.
- Bad, because the archive alone rarely explains a new subject: in the real
  checks archive sources were cited far less often than web pages.
