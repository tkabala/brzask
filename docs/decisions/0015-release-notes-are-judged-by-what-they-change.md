---
status: accepted
date: 2026-10-21
---

# Release notes are judged by what they change

## Context and problem statement

Many interests are about software, and the best source on a project is often
its release feed (`github.com/<owner>/<repo>/releases.atom`). Release feeds
are noisy: most entries are patch versions, dependency bumps and release
candidates, and their titles are only version numbers. Should release notes
be filtered out as noise, ranked like any article, or treated as their own
kind of candidate?

## Decision drivers

- A release that changes how the reader works is worth a place in the 7.
- A version bump is not, however well the project matches an interest.
- A headline like `v2.8.0-rc.1` says nothing in a digest.

## Considered options

- Drop release feeds from the digest.
- Rank release notes like any other article.
- Mark them as release notes, and tell every prompt to judge them on their changes.

## Decision outcome

Chosen option: mark and judge on substance. A candidate is release notes
when its source has the `release` kind or its feed URL ends in
`/releases.atom`. The ranking prompt shows it as `[RELEASE]` and says to rank
one high "only if it brings a genuinely new feature or a change the reader
would want to know about", and routine bumps, dependency or security
patches and bugfix batches low. The selection prompt names the project and
the version in the title when the headline is only a tag ("Caddy 2.8.0,
first release candidate"). The composite judge's novelty question asks what
a release changes, not that a version shipped.

### Evidence

From daily use, as of 2026-10-21, with 13 active release feeds and about 31
release notes in a daily pool of 200:

| | Stored | Shown | Opened | Opened of shown |
|---|---|---|---|---|
| Release notes | 537 | 92 | 3 | 3.3% |
| Other articles | 4,686 | 588 | 33 | 5.6% |

Release notes reach the digest at least as often as other articles (17% of
those stored, against 13%) and are opened less often. Three were opened,
so they are not noise to the reader, but the prompts may still let too
many through.

### Consequences

- Good, because a release with real changes competes on equal terms.
- Good, because digest titles of releases are readable.
- Bad, because the measured open rate of release notes is lower than the
  rest, so the line between a release worth reading and a routine one is
  not yet where the reader would draw it.

## Pros and cons of the options

### Drop release feeds

- Good, because it removes the noise.
- Bad, because it removes the releases that were opened, and the reason to
  follow a project's feed at all.

### Rank like any article

- Good, because there is nothing to special-case.
- Bad, because a project that matches an interest by name pulls every patch
  release up.

### Judge on substance

- Good, because the model reads what changed.
- Bad, because it is a soft instruction, and the numbers above say it is
  not yet strict enough.

## More information

Revisit with `brzask replay` and a stricter release instruction in the
ranking prompt; a change is worth keeping if the replay keeps its opens with
fewer release notes picked.
