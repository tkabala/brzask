# Feed

The digest is also an Atom feed, for reading it in any feed reader:
Miniflux, FreshRSS, NetNewsWire, Feedly and the like.

## Subscribe

Readers send no login, so the feed's URL carries a token of its own:

```console
$ brzask tokens create reader --scope feed
brz_...
```

With Docker Compose, run it in the API container:
`docker compose exec api brzask tokens create reader --scope feed`.

Then subscribe to:

```text
https://news.example.com/feed?token=brz_...
```

With `AUTH_MODE=none` the feed needs no token: `https://news.example.com/feed`.

## What is in it

- The last seven days with a digest, newest first, in digest order within a
  day: up to 49 entries. A reader that polls once a week misses no day.
- Each entry has the digest's title, the summary and why it matters, the
  interest it was picked for (as its category) and the source (as its author).
  The feed's language is `DIGEST_LANGUAGE`.
- Entry links go through [`/open`](api.md#opening-articles), signed, so
  opening an article from the reader counts as an open, the signal brzask
  learns from. Readers that fetch every article on their own (full-text
  or "readability" options) would count each one as opened: turn that off
  for this feed.
- Readers can poll as often as they like: the feed answers `304 Not
  Modified` to `If-None-Match` with its last `ETag`.

## The token

- A `feed` token opens only `/feed`. The JSON API refuses it, so a URL that
  leaks through a reader's service or a log gives away the digest and
  nothing else.
- brzask writes `token=REDACTED` in its access log and traces. Your reverse
  proxy logs query strings too; see [Reverse proxy](reverse-proxy.md#feed-readers-and-open-links).
- `brzask tokens list` shows when it was last used; `brzask tokens revoke reader`
  stops it at once. Make one token per reader, so each can be revoked alone.
