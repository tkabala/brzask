---
status: accepted
date: 2026-10-21
---

# One image for every command, serving the web app itself

## Context and problem statement

A running instance needs migrations, the API, the worker and the web app.
They could ship as separate images (an API image, a worker image, an nginx
image with the built frontend) or as one. What is the unit of release?

## Decision drivers

- Installing and upgrading is one image tag, with one signature and one SBOM
  to verify.
- The API, the worker and migrations must always be the same version.
- No reverse proxy required to see the app; one can still be put in front.
- A small attack surface: non-root, no build tools or package manager at run time.

## Considered options

- One multi-stage image; the command (`api`, `worker`, `migrate`, `setup`,
  any `brzask` subcommand) chooses the role, and the API serves the built web app.
- Separate images per role, the frontend in nginx.

## Decision outcome

Chosen option: one image. A Node stage builds the frontend once for every
platform, a Python stage installs the locked dependencies with uv, and the
runtime stage on `python:3.13-slim` copies both, runs as uid 10001, and has
`ENTRYPOINT ["brzask"]` with `api` as the default command. The API serves the
web app's files after its own routes: hashed assets as immutable, every
other path as `index.html` without caching, so client-side routes load
directly, and unknown `/api/*` paths stay JSON errors. The compose file runs
the image three times: `migrate` once, then `api` and `worker`.

Each release is published for amd64 and arm64, scanned with Trivy (a
fixable critical finding stops the release before anything is pushed),
signed with cosign and shipped with an SBOM and build provenance.

### Evidence

The image is 479 MB unpacked and about 103 MB compressed; the Python
environment is 228 MB of it. A multi-arch build takes about 76 seconds
locally with a warm cache. The first scan found a real issue (a certifi
bundle with compromised roots, also vendored by pip), fixed by updating
certifi and removing pip from the runtime image.

### Consequences

- Good, because one tag describes the whole instance, and versions cannot
  drift between roles.
- Good, because a quick look at the app needs no proxy.
- Good, because every CLI command, from `seed-demo` to `replay`, runs in the
  installed image with `docker compose run`.
- Bad, because the worker carries the web app's files it never serves, and
  the API carries pipeline dependencies.
- Bad, because static files are served by Python. For one reader that is no
  load; a proxy can cache them if needed.

## Pros and cons of the options

### One image

- Good, because one thing to pull, verify and upgrade.
- Bad, because every role pays for the size of all of them.

### Separate images

- Good, because each image is smaller and nginx serves static files faster.
- Bad, because three tags must move together, and the frontend's image needs
  its own proxy setup to reach the API.

## More information

[Installation](../install.md) covers tags, upgrades and verifying the signature.
