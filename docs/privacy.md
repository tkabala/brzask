# Privacy

brzask runs on your machine and keeps its data in your database. It sends no
telemetry, does not check for updates and has no account with anyone. Every
request it makes to another machine is listed on this page, with the setting
that controls it.

## The web app

The web app talks only to the server it was loaded from: its scripts, styles,
fonts and icons are served by brzask itself, and its Content Security Policy
lets the browser connect nowhere else. Links you open from a digest leave
without a `Referer` header, so a site never learns the address brzask is
served at.

The one exception is the API's interactive reference at `/api/v1/docs`: opening
it makes the browser load Swagger UI from `cdn.jsdelivr.net` and an icon from
`fastapi.tiangolo.com`.

## What the server sends, and to whom

Requests to the sites you read go to those sites, through `FETCH_PROXY` when it
is set. Requests to services go to the address configured for each.

| Request | When | Sent to | What it carries | Setting |
| --- | --- | --- | --- | --- |
| Feeds | Every digest, source review and discovery | Each source's site | The feed URL; `If-None-Match` / `If-Modified-Since` from the last fetch | `FETCH_PROXY`, `ALLOWED_PRIVATE_NETWORKS` |
| Article pages and `robots.txt` | For the articles in the daily top 15, and the pages a deep dive or conversation reads | The article's site | The page URL | `EXTRACTORS`, `FETCH_PROXY` |
| YouTube captions | For a video among the daily top 15 | `youtube.com` | The video ID | `FETCH_PROXY` |
| Feed lookups | When you add a source, discovery checks a candidate, or the weekly visited check looks at the sites of articles you opened | That site | The URL | `FETCH_PROXY`, `VISITED_AT`, `DISCOVERY_AT` |
| GitHub API | When a feed lookup meets a GitHub repository | `api.github.com` | The repository name | — |
| Chat model | Ranking, selection, briefs, deep dives, conversations, discovery | `LLM_BASE_URL` (OpenRouter by default) | Article titles, snippets and texts; your interests and notes; titles, topics and sources of articles you opened recently; your questions in a conversation | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Embeddings | For new articles, and for each search | `EMBEDDING_BASE_URL` (the chat model's API by default) | The text of each article in the daily top 15 (its snippet when the page could not be read); your search text | `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY` |
| Judgements | Same-day duplicates; ranking with `DIGEST_RANKING=judge` | `JUDGE_BASE_URL` (the chat model's API by default) | Article titles and snippets; your interests and recently opened titles | `JUDGE_BACKEND`, `JUDGE_BASE_URL`, `JUDGE_API_KEY` |
| Hosted page readers | When the extractors before them could not read a page | `r.jina.ai` (in the default `EXTRACTORS`), Firecrawl or Crawl4AI | The page URL | `EXTRACTORS`, `JINA_API_KEY`, `FIRECRAWL_BASE_URL`, `FIRECRAWL_API_KEY`, `CRAWL4AI_BASE_URL`, `CRAWL4AI_API_TOKEN` |
| Web search | Source discovery; a deep dive or conversation when you ask it to search | SearXNG, the Brave Search API (`api.search.brave.com`) or an online model through the chat model's API | Search queries built from your interests or from the article | `WEB_SEARCH`, `SEARXNG_URL`, `BRAVE_API_KEY`, `WEB_SEARCH_MODEL` |
| Notifications | A digest or deep dive is ready, a run failed | Each Apprise URL | The digest's titles, or the run that failed; links to brzask when `BASE_URL` is set | `NOTIFY_URLS` |
| Traces and metrics | Continuously, when configured | `OTEL_EXPORTER_OTLP_ENDPOINT` | Request routes and timings, database statements, outgoing request URLs | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Error reports | When an error is not handled, when configured | `SENTRY_DSN` | See below | `SENTRY_DSN` |

Without `WEB_SEARCH`, source discovery is off and deep dives and conversations
answer from the article and the archive only. With `LLM_BASE_URL` pointing at a
local server such as Ollama, and `EXTRACTORS` without `jina`, nothing about your
reading leaves your network except the fetches of the sites you read.

Every outgoing request names itself with the `User-Agent` `brzask/<version>`
and a link to the project.

## Error reports

Sentry is off unless `SENTRY_DSN` is set. A report holds the exception, its
stack trace with the surrounding source lines, the request's method, URL and
query string, the release and the component (`api` or `worker`). It does not
hold the values of variables, cookies, request headers or bodies, or anything
Sentry would infer about the user (`send_default_pii` is off); the feed's token
and API tokens are removed from URLs and messages, and notification requests are left out of
the breadcrumbs. A secret that an error message quotes would still reach it.

## What is kept, and where

Articles, their texts, briefs, deep dives, conversations, your interests and
when you opened what stay in the Postgres database you run. Logs go to the
containers' standard output. Deleting the database deletes all of it; see
[Backup and restore](backup.md).
