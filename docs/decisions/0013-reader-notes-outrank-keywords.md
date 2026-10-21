---
status: accepted
date: 2026-10-21
---

# Reader notes outrank keywords

## Context and problem statement

An interest needs to say what the reader wants, and often what they do not.
Keywords are good at the first: "pgvector", "replication" and "query planner"
pull a topic towards the right articles. They cannot say no. A keyword that
names a project also matches its funding news, and a keyword shared by two
projects matches both. How should an interest express what to skip?

## Decision drivers

- The reader writes interests once and should not have to maintain lists.
- "Skip" has to work in every prompt that reads interests: ranking,
  selection and the discovery judge.
- No string matching on titles: it misses paraphrases and hits false friends.

## Considered options

- Keywords only.
- Keywords plus exclusion keywords, matched in code.
- Keywords plus a free-text note per interest that the prompts put above the keywords.

## Decision outcome

Chosen option: a free-text note per interest that outranks its keywords.

Each interest has a topic, keywords and notes. The shared prompt block lists
an interest as `topic: keywords [reader note: …]`, the note after the
keywords, and the ranking prompt says that a note "is the reader's own
guidance for that topic and outranks its keywords: rank anything a note says
to skip low, even when the keywords match". The discovery judge reads the
same rule when it decides whether a feed serves the interests. Keywords can
only widen what a topic covers; only a note can narrow it.

The UI suggests the form `want: …; skip: …`, but any text works.

### Evidence

No replay compares notes with exclusion keywords; the choice follows from
what the notes in daily use say. Three of nine active interests carry a
note, all with a "skip:" part, and each excludes something a keyword
cannot: funding rounds, partnerships and leaderboard churn around model
releases; releases of a model family that shares its name with the agent of
interest; general news about a distribution that one desktop is built on.
Each needs judgement about what an article is about, not about which words
it contains.

### Consequences

- Good, because a reader can say what they skip in their own words.
- Good, because the same note steers ranking, selection and discovery.
- Bad, because the effect depends on the model following the instruction;
  it can be checked only with `brzask replay` on a history where the note
  already existed.
- Bad, because notes are free text, so nothing validates them.

## Pros and cons of the options

### Keywords only

- Good, because it is simple.
- Bad, because it can only widen, never exclude.

### Exclusion keywords

- Good, because the effect is exact and visible.
- Bad, because a word in a title does not say what the article is about,
  and the reader ends up maintaining two lists.

### Notes over keywords

- Good, because "skip funding news" covers every wording of funding news.
- Bad, because it is a soft rule the model may bend.

## More information

The prompts are in `backend/src/brzask/prompts/` (`_interests.md` is the
shared block).
