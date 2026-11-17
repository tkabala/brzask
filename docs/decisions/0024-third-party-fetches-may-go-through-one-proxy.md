---
status: accepted
date: 2026-11-17
---

# Third-party fetches may go through one proxy; the address guard stays in brzask

## Context and problem statement

Some sites refuse requests from data-centre addresses. On 2026-11-16 the
captions of the 14 most recent digest videos were fetched from a hosted
server and from a home network: 0 of 14 succeeded from the server (every
request was blocked, over IPv6 too) and 14 of 14 from home. Feeds and pages
can be refused the same way. An instance on a hosted server needs a way to
send its fetches of third-party sites out through another network, without
loosening the check that keeps those fetches off private addresses
([0023](0023-third-party-text-is-data-and-its-reach-is-bounded.md)).

## Decision drivers

- The address guard must hold whatever the proxy does: a URL a third party
  names must not reach the owner's network through it.
- Services the owner configured (LLM, embeddings, search, extraction
  services, notifications) are not the problem and should not change path.
- One setting, nothing to run for an instance that does not need it.

## Considered options

- A proxy setting per site or per client (captions, pages, feeds).
- The environment's `HTTP_PROXY` and `HTTPS_PROXY` for every client.
- One setting, `FETCH_PROXY`, for every fetch of a third-party site, with
  the address guard kept in brzask.

## Decision outcome

Chosen option: one setting for third-party fetches with the guard kept in
brzask.

Every client built for URLs third parties name goes through `FETCH_PROXY`
when it is set. brzask still resolves the host and refuses the request when
any address is not allowed, then asks the proxy for a tunnel to the checked
IP address: an HTTP `CONNECT ip:port` or a SOCKS5 connect with an IPv4 or
IPv6 address, never a host name. Plain-HTTP targets go through a tunnel too,
so the proxy never receives a URL or a name to resolve. TLS still verifies
the host name and the request still names it. The proxy's own address is the
one connection the guard does not check: the owner configured it, and it is
usually a private or tailnet address.

### Consequences

- Good, because a hosted instance can fetch what only a home network gets.
- Good, because the guard does not depend on the proxy: a name that
  resolves to a private address is refused before the proxy is contacted.
- Bad, because the proxy must allow `CONNECT` to ports 80 and 443.
- Bad, because a proxy is a second way into the network it sits in: it
  should not reach the owner's LAN beyond what it needs (the guard is the
  first line, the proxy's firewall the second). `ALLOWED_PRIVATE_NETWORKS`
  keeps its meaning and is evaluated from brzask's resolver, so a LAN feed
  reached through the proxy needs the proxy to reach that address.
- Bad, because `https://` proxies (TLS to the proxy itself) are not
  supported; `http://` and `socks5://` are.
- Neutral, because configured services always go direct, whatever
  `FETCH_PROXY` says.

## Pros and cons of the options

### A proxy per site or per client

- Good, because only the sites that refuse data-centre addresses pay the
  extra hop.
- Bad, because which sites refuse changes over time, and each new client
  would need its own setting.

### The environment's `HTTP_PROXY`

- Good, because it needs no code.
- Bad, because it also moves the configured services, which may run on
  the owner's own network.
- Bad, because the proxy would resolve the names, so the address guard
  would check one answer and the proxy connect to another.

### One setting with the guard kept in brzask

- Good, because the guard keeps its place and its guarantees.
- Bad, because brzask opens the tunnel itself instead of using the HTTP
  library's proxy support, which hands the proxy the host name.

## More information

- [Installation](../install.md#fetching-through-a-proxy): running a small
  forward proxy at home.
- [Configuration](../configuration.md): `FETCH_PROXY`,
  `ALLOWED_PRIVATE_NETWORKS`.
