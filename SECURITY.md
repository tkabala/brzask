# Security policy

## Supported versions

Fixes go into the latest release only. Update to it before reporting, if you
can.

## Reporting a vulnerability

Please report it privately through GitHub:
[Report a vulnerability](https://github.com/tkabala/brzask/security/advisories/new)
on the repository's Security tab. Do not open a public issue.

Say what is affected, how to reproduce it and what an attacker gains. You will
get an answer within a week. Once a fix is released, the advisory is published
with credit to you, unless you would rather not be named.

## What brzask protects against

- **Access to the web app and API.** A password (argon2 hash) and a session
  cookie (`HttpOnly`, `SameSite`, `Secure` over HTTPS), or a reverse proxy that
  names the user, accepted only from `TRUSTED_PROXIES`. Requests that change
  something need a CSRF token. Agents use API tokens limited to a scope; see
  [Authentication](docs/api.md) and [Agents](docs/agents.md).
- **The browser.** A Content Security Policy that allows scripts only from
  brzask itself, `frame-ancestors 'none'`, `nosniff` and no `Referer` to the
  sites you open.
- **Fetches made for you.** Feeds, pages and search results are fetched only
  from public addresses unless `ALLOWED_PRIVATE_NETWORKS` allows a private one;
  the address is checked after DNS resolution and on every redirect, and the
  connection goes to the checked address.
- **Text from other sites.** Article texts and search results reach the LLM as
  data, never as instructions, and what an LLM step can do with them is bounded
  ([ADR 0023](docs/decisions/0023-third-party-text-is-data-and-its-reach-is-bounded.md)).
- **The image.** Each release image is scanned before it is pushed, carries an
  SBOM and build provenance, and is signed with cosign
  ([verifying it](docs/install.md)).

## What it does not protect against

- `AUTH_MODE=none` turns off all login: use it only on a machine nobody else
  can reach.
- brzask over plain HTTP sends the session cookie in the clear. Put it behind a
  reverse proxy with TLS, which also sets HSTS
  ([Reverse proxy](docs/reverse-proxy.md)).
- The LLM, embedding, judge and search providers you configure see what is
  sent to them; [Privacy](docs/privacy.md) lists what that is.
- Anyone with access to the database or the `.env` file has everything.
