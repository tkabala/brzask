---
status: accepted
date: 2026-10-20
---

# Trafilatura as the default page extractor, a hosted reader as fallback

## Context and problem statement

The digest needs the text of its top 15 candidates: embeddings for deduplication
take the first 4,000 characters, and the selection prompt shows the first 3,000.
Extractors are tried in the order of `EXTRACTORS`. Which one should come first
when the feed does not carry the full article: trafilatura, which fetches the
page and extracts it locally, or a hosted reader such as Jina Reader?

## Decision drivers

- Usable text for as many articles as possible.
- The text must be the article, not the page around it: only its start is
  embedded and shown to the model.
- No account or API key needed for the default setup.
- Latency and cost of a daily run.
- Article URLs stay on the server unless a hosted service is chosen.

## Considered options

- `feed,trafilatura,jina`: trafilatura first, Jina Reader when it fails.
- `feed,jina,trafilatura`: Jina Reader first.
- `feed,trafilatura`: no hosted reader at all.

## Decision outcome

Chosen option: `feed,trafilatura,jina`, because trafilatura gets usable text as
often as the hosted reader, an order of magnitude faster and without a key, and
its text is the article alone. Jina Reader stays as the fallback because it
gets a few pages trafilatura cannot.

### Evidence

`brzask extract-bench` on 60 links stored in the last 10 days, from 31 sites (at
most 3 per site), every extractor on every link, through the same robots.txt,
site and usable-text rules as a digest run:

| Extractor | Tried | Usable | Median words | Median latency | p90 latency | Tokens |
|---|---|---|---|---|---|---|
| feed | 60 | 8 (13%) | 1,394 | 0 ms | 0 ms | – |
| trafilatura | 54 | 50 (93%) | 918 | 262 ms | 796 ms | – |
| Jina Reader (no key) | 54 | 49 (91%) | 1,644 | 3,366 ms | 8,507 ms | 312,866 |

Six links were Reddit and YouTube pages, which only the feed may read. Words
are counted without Markdown link targets and images.

- **Whole page instead of the article.** On 18 of the links both got, Jina's text
  had more than twice trafilatura's words. Checked by hand, the difference is
  the page around the article: on a Phoronix news item, trafilatura returned the
  article (141 words) and Jina added navigation, "related news" and the footer
  (764 words); on an InfoQ article, the article is lines 121–149 of about 300.
  On the InfoQ page, the first 4,000 characters of Jina's text, the part
  that gets embedded, are all navigation.
- **Where each one fails.** Both got HTTP 403 from a Medium-hosted blog (the
  feed carries those articles in full). Jina got 403 on all three GitHub release
  pages, trafilatura none. Jina alone got a JavaScript-rendered page and one
  page that answered a direct fetch with 404.
- **Cost.** Jina reported 312,866 tokens for 49 pages (about 6,400 per page),
  billed with a key. Without a key it allows 20 requests a minute.
- A second run of feed and trafilatura on 176 links from 76 sites: trafilatura
  usable on 150 of 165 (91%), median 277 ms.

### Consequences

- Good, because the default works without any account, fetches nothing through
  a third party, and the top 15 are extracted in seconds.
- Good, because the embedded and prompted text starts with the article.
- Bad, because pages that need JavaScript fall back to Jina Reader, whose text
  starts with the page's navigation. Its main-content options were not tried.
- Bad, because a site can start answering trafilatura's plain fetches with a
  bot check (the JetBrains blog did after a few dozen requests); the block
  phrases catch that page and the chain moves on.

## Pros and cons of the options

### `feed,trafilatura,jina`

- Good, because it is fast, free and returns the article alone.
- Good, because the hosted reader still covers JavaScript pages.
- Bad, because a page fetched by Jina carries navigation into embeddings.

### `feed,jina,trafilatura`

- Good, because a rendering reader handles JavaScript pages first time.
- Bad, because its text is the whole page, it is about 13 times slower, and
  without a key a run is limited to 20 requests a minute.

### `feed,trafilatura`

- Good, because no article URL ever leaves the server.
- Bad, because the few pages only a rendering reader gets fall back to the
  feed snippet.

## More information

Run `brzask extract-bench` again before changing `EXTRACTORS` defaults, and
when adding Firecrawl or Crawl4AI (`--extractors trafilatura,crawl4ai`). The
same runs measured `FEED_MIN_CHARS` and `BLOCK_PAGE_MAX_CHARS`; see their
comments.
