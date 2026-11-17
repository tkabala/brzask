# Installation

brzask runs as four containers from one image: `db` (Postgres with
pgvector), `migrate` (creates or upgrades the schema, then exits), `api`
(the HTTP API and the web app) and `worker` (runs the pipelines on their
schedule). [`deploy/compose.yaml`](https://github.com/tkabala/brzask/blob/main/deploy/compose.yaml)
starts all of them.

## Quickstart

With Docker and Compose 2.24 or newer:

```sh
mkdir brzask && cd brzask && curl -fsSLO https://raw.githubusercontent.com/tkabala/brzask/main/deploy/compose.yaml
docker compose run --rm setup
docker compose up -d
```

`setup` asks for a login password and an LLM API key (an
[OpenRouter](https://openrouter.ai) key covers ranking and embeddings; leave
it empty for a local server) and writes them, with generated database and
session secrets, to `./secrets`, one file per secret. Running it again keeps
the files that exist. Then open <http://localhost:8000>.

## Configuration

Settings go in a `.env` file next to `compose.yaml`; every variable is
described in [Configuration](configuration.md) and listed with its default
in [`.env.example`](https://github.com/tkabala/brzask/blob/main/.env.example).
Models and endpoints other than the OpenRouter defaults are covered in
[Providers](providers.md).
Set `TZ` (for example `TZ=Europe/Warsaw`) so the daily digest is built in
your morning. The secrets `setup` writes (database password, login, session
secret, LLM API key, Crawl4AI token) are always read from `./secrets`
through `<NAME>_FILE` variables; compose ignores `DB_PASSWORD`,
`LLM_API_KEY`, `AUTH_PASSWORD_HASH`, `AUTH_SESSION_SECRET` and
`CRAWL4AI_API_TOKEN` in `.env`, so a `.env` copied from `.env.example` works
as it is. To change one of them, edit its file and restart. Other secrets,
such as `JINA_API_KEY`, go in `.env`.

Compose itself reads a few variables from the same `.env`:

| Variable | Default | What it sets |
|---|---|---|
| `BRZASK_IMAGE` | `ghcr.io/tkabala/brzask:latest` | Image for `migrate`, `api` and `worker` |
| `BRZASK_PUBLISH` | `127.0.0.1:8000` | Host address and port of the web app; `8000` alone listens on every address |
| `BRZASK_SECRETS` | `./secrets` | Directory of the secret files |
| `COMPOSE_PROFILES` | | Optional services, below |
| `GRAFANA_PUBLISH` | `127.0.0.1:3000` | Host address and port of Grafana (`observability` profile) |

The web app is published on the loopback address only. To reach it from
other machines, put a [reverse proxy](reverse-proxy.md) with TLS in front
(at a host name of its own or [under a path](reverse-proxy.md#under-a-path)),
or set `BRZASK_PUBLISH`. Back up the database with `pg_dump` as described in
[Backup and restore](backup.md).

## Optional services

| Profile | Service | Enable with, in `.env` |
|---|---|---|
| `crawler` | [Crawl4AI](https://github.com/unclecode/crawl4ai): a headless browser for pages plain HTTP cannot read | `COMPOSE_PROFILES=crawler`, `EXTRACTORS=feed,trafilatura,crawl4ai` |
| `search` | [SearXNG](https://github.com/searxng/searxng): web search for source discovery, without a paid API | `COMPOSE_PROFILES=search`, `WEB_SEARCH=searxng` |
| `observability` | Collector, Prometheus, Tempo and Grafana with a dashboard of runs, cost and opens; see [Observability](observability.md) | `COMPOSE_PROFILES=observability`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` |

Several at once: `COMPOSE_PROFILES=crawler,search`. Their secrets come from
`setup` too. The Crawl4AI image is large (about 8 GB) and wants 2 GB of
memory.

## Fetching through a proxy

Some sites refuse requests from data-centre addresses. Set `FETCH_PROXY` to
send every fetch of a third-party site (feeds, article pages, robots.txt,
discovery) through a forward proxy on another network, for example at home:

```bash
FETCH_PROXY=http://proxy.home.example:8888
# or with credentials, or SOCKS5:
FETCH_PROXY=socks5://user:password@proxy.home.example:1080
```

brzask still resolves every host and refuses non-public addresses itself,
then asks the proxy for a tunnel to the checked IP address, never a host
name; plain-HTTP pages go through a tunnel too. So the proxy must allow
`CONNECT` to ports 80 and 443. `https://` proxies are not supported.
Services you configured (LLM, embeddings, search, extraction services,
notifications) are always reached directly.

YouTube captions are the exception to the address check: they are fetched by
a library that hands the proxy the host name (`www.youtube.com`, a public
site). Measured in November 2026: captions came through for 14 of 14 recent
digest videos from a home connection and for none of them from a hosted
server, which YouTube answered with "request blocked". A home address is not
a guarantee, though: the same month it was itself refused for hours after
many caption requests in a row. Videos whose captions are refused fall back
to the feed description as text, with or without a proxy.

Keep the proxy off your LAN: the address check in brzask is the first line,
a firewall on the proxy host that drops connections to private networks is
the second (see below). A LAN feed listed in `ALLOWED_PRIVATE_NETWORKS` is
then reached through the proxy, which needs to reach that address.

### A proxy with tinyproxy

[tinyproxy](https://tinyproxy.github.io/) on a machine at home. Add or change
these lines in the packaged `/etc/tinyproxy/tinyproxy.conf` (keep its
`User`, `Group`, `LogFile` and `PidFile`; a short replacement file drops
them). tinyproxy rejects a comment at the end of a directive line and does
not start, so comments go on their own lines:

```text
Port 8888
# The proxy host's private address; without Listen, every interface.
Listen 192.168.1.20
# The address the proxy sees the brzask server's connections come from.
Allow 192.168.1.6
ConnectPort 443
ConnectPort 80
```

`Allow` must name the address as the proxy sees it. Through a VPN subnet
router such as Tailscale that is the router's LAN address, not the brzask
server's VPN address, and every node routed through that router is then
admitted too. If unsure, try a request and read `Unauthorized connection
from "..."` in the tinyproxy log.

`ConnectPort` restricts `CONNECT` only. tinyproxy still forwards a plain
`GET http://192.168.1.1/` to any host, your router's web page included.
brzask never sends that (it always tunnels to an address its own check
passed), but anyone else allowed to use the proxy could. So block private
destinations for the proxy's user. This nftables table does it and keeps DNS
to the LAN resolver (here `192.168.1.8`) open:

```text
# /etc/tinyproxy/no-lan.nft
table inet tinyproxy_guard
delete table inet tinyproxy_guard
table inet tinyproxy_guard {
	chain output {
		type filter hook output priority filter; policy accept;
		meta skuid != "tinyproxy" accept
		ct state established,related accept
		ip daddr 192.168.1.8 meta l4proto { udp, tcp } th dport 53 accept
		ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/3 } reject
		ip6 daddr { ::1, fc00::/7, fe80::/10, ff00::/8 } reject
	}
}
```

Load it whenever the service starts, with a drop-in
(`systemctl edit tinyproxy`):

```ini
[Unit]
# Listen names a private address: wait for the network at boot. Where
# nftables.service flushes the ruleset on start, load the table after it.
Wants=network-online.target
After=network-online.target nftables.service

[Service]
ExecStartPre=/usr/sbin/nft -f /etc/tinyproxy/no-lan.nft
```

Reloading `nftables.service` later drops the table until tinyproxy restarts.
systemd's `IPAddressDeny=` is the shorter route, but it may not be enforced
inside containers such as LXC (it was not in a test), so check with a plain
`curl -x http://192.168.1.20:8888 http://192.168.1.1/`: it must fail.

### An SSH tunnel instead

Without installing anything at home, an SSH SOCKS tunnel started on the
brzask server, bound to an address the containers reach (the Docker bridge,
`172.17.0.1` by default):

```bash
ssh -N -D 172.17.0.1:1080 user@home.example
```

```bash
FETCH_PROXY=socks5://172.17.0.1:1080
```

Why the address check stays in brzask is recorded in
[ADR 0024](decisions/0024-third-party-fetches-may-go-through-one-proxy.md).

## Images

Releases are published to `ghcr.io/tkabala/brzask` for amd64 and arm64,
tagged with the version (`0.1.0`, `0.1`) and `latest`. Pin a version in
`BRZASK_IMAGE` to upgrade on your own schedule; `docker compose pull && docker
compose up -d` upgrades, and `migrate` updates the schema on the way.

Each image carries an SBOM and build provenance, and is signed with
[cosign](https://github.com/sigstore/cosign) by the release workflow:

```sh
cosign verify ghcr.io/tkabala/brzask:latest \
  --certificate-identity-regexp '^https://github.com/tkabala/brzask/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Commands

Every `brzask` command runs in the image, for example:

```sh
docker compose exec api brzask status
docker compose exec api brzask sources add https://example.com/blog
docker compose run --rm migrate seed-demo   # fill an empty instance with demo data
docker compose exec worker brzask notify test  # check NOTIFY_URLS
```

To hear when the digest is ready or a run fails, see [Notifications](notifications.md).

A source is found from any page of a site: the page itself when it is a feed,
the feeds it links to, then the usual feed locations. GitHub repositories
resolve to their release notes and YouTube channels to their video feed.
Reddit cannot be followed: it stopped serving RSS on 2026-11-13 and its API
accepts no new apps, so Reddit links are refused when adding sources.
Subreddits added earlier fail to fetch and the weekly source review marks them
dead after two weeks; mute them right away with `brzask sources mute`.

## Bringing your feeds

Feed readers export their subscriptions as an OPML file. Import it on the
Sources page, or from the command line:

```sh
docker compose exec -T api brzask sources import /dev/stdin < feeds.opml
docker compose exec -T api brzask sources import --active /dev/stdin < feeds.opml
```

Every feed is fetched before it is added. When its URL no longer works, the
site's page is read for the feed it points to now. A feed that cannot be read
is listed and skipped, including one that is only down for the moment;
importing the file again later tries it again. New feeds wait on the Sources page for a decision,
like the ones brzask proposes itself; `--active` (or "Read them right away"
on the page) follows them from the next digest instead. Feeds that are already
sources, in any status, are left as they are, so importing a file twice adds
nothing. On the page, checking stops after 45 seconds so a large file does not
outlast a proxy's timeout; import the same file again to continue where it
stopped. The command line has no such limit.

Export goes the other way, for a feed reader or another brzask:

```sh
docker compose exec -T api brzask sources export > brzask-sources.opml
docker compose exec -T api brzask sources export -s active -s muted > all.opml
```
