---
status: accepted
date: 2026-11-24
---

# A conversation answers from stored material; searching is the reader's action

## Context and problem statement

From an article's brief or its deep dive report the reader can ask follow-up
questions, each prompted by the last answer, in one conversation kept with the
article. The material is already stored: the article's text, its brief, its
finished deep dives and their sources. Some questions go beyond it: what
changed since, what something costs today. Where should answers come from, and
who decides when to look further?

## Decision drivers

- Third-party text is data ([ADR 0023](0023-third-party-text-is-data-and-its-reach-is-bounded.md)):
  it must not choose what brzask does next, and what it can reach stays bounded.
- An answer read on a phone must arrive in seconds, within one request that a
  reverse proxy does not cut (commonly at 60 s).
- Every link an answer shows must be one brzask gathered, as in reports
  ([ADR 0026](0026-deep-dives-follow-a-fixed-pipeline-and-cite-only-gathered-sources.md)).
- The cost of asking is small, known and counted in the spending limits.

## Considered options

- The model decides when to search (a tool it may call while answering)
- Closed book: stored material only, never a search
- Stored material by default, one bounded search round when the reader taps it

## Decision outcome

Chosen option: "stored material by default, a search round on the reader's
tap", because an answer from stored material takes seconds and a fraction of
a cent, and the reader, not text the model has read, decides when to spend
tens of seconds and about a cent on a search.

- **An answer** is one LLM call inside the request, bounded at 45 seconds. The
  model sees the reader's interests, the article (source 1), its brief, its
  finished deep dives, the conversation's numbered sources and the last 20
  exchanges. Everything written by publishers or by a model summarising them
  is inside `<untrusted>` marks; the questions are outside.
- **The answer is structure**: paragraphs with source numbers, `enough`, and
  up to three suggested follow-ups. Numbers not among the conversation's
  sources are removed; numbers written into the text are stripped; nothing
  model-written is rendered as HTML or Markdown.
- **`enough: false`** when the material does not answer the question,
  including questions about the present (the latest version, today's price)
  that the material can only answer as of its writing. The search control is
  under every latest answer and becomes the main button when `enough` is false.
- **A search round** runs in the background: one call plans at most two web
  and one archive query, five web pages and three archive articles are read
  with the deep dive's functions (address guard, robots rules, `FETCH_PROXY`),
  new sources get the next numbers, and the answer is written again with the
  new numbers named. When nothing new is found, or the rewrite cites none of
  it, the answer carries a note saying so.
- One answer is in progress per conversation at a time. Source numbers never
  change, so earlier answers keep citing the right entries. Searched text
  shares 60,000 characters in the prompt, newest first, whole sources only.
- Every answer stores its usage; the spending limits add conversations to runs.

### Evidence

A real check on a copy of the production database (2026-11-24) with three
articles: one with a deep dive, one without, one video read from its
transcript. Eleven questions (starters, suggestions and the reader's own, one
in English) and two search rounds were asked through the web app at phone
width, then asked again after the prompt changes below.

- An answer took 2-35 seconds (median about 7) and cost $0.0002-0.0016; a
  search round took 24-51 seconds and cost $0.012-0.013, of which the two web
  searches were $0.011. The whole first run cost $0.030.
- Prompts were 9,500-17,000 characters before a search and up to 72,600 after
  one; one round's stored text (66,000 characters) already exceeded the
  60,000-character share.
- `enough: false` was right each of the 4 times it was set in the first run.
  It was wrong once: "is it fixed in the latest version?" was answered as
  current fact from a dated article.
- First-run problems: an English question answered in Polish; starters
  answered in 1,500-1,950 characters (2.5 screens) that re-summarised the
  article; source numbers repeated in the text; suggestions the material could
  not answer offered right after a "not enough" answer; a search round whose
  rewrite ignored the one new source that answered the question.
- After the prompt changes (answer about 600 characters, the question's
  language, questions about now, no repetition, the article over its brief,
  suggestions the material answers, new sources named in the rewrite): answers
  were 276-817 characters (median 392), the English question got an English
  answer, the "latest version" question was `enough: false`, and its search
  round's rewrite cited the release notes it found.

### Consequences

- Good, because nothing a page says can make brzask search or fetch; the
  reader's tap starts every round, and a round's calls, queries, pages and
  characters are fixed.
- Good, because an answer costs about a twentieth of a cent and a round about
  a cent, and both count towards the limits.
- Bad, because an answer from stored material can be out of date; it says so
  only when the model notices the question is about the present.
- Bad, because a search round is only as good as its results: in the check,
  archive hits included video pages whose stored text was page chrome, the
  same page appeared under two URLs, and a page that refused the fetch was
  retried for 16 seconds.
- Bad, because searched text makes every later answer in the conversation
  larger (up to 60,000 more characters per prompt).

## Pros and cons of the options

### The model decides when to search

- Good, because the reader does not have to notice that the material ran out.
- Bad, because text the model has read would decide to spend money and fetch
  pages, and an answer's duration and cost would have no fixed bound.

### Closed book

- Good, because nothing outside brzask is ever fetched for a question.
- Bad, because questions about what happened since the article cannot be
  answered at all; in the check one round found the fix the question asked about.
