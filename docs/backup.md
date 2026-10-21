# Backup and restore

Everything brzask knows lives in Postgres: sources, interests, articles with
their embeddings, digests, opens, runs and the change log. Keep the `secrets`
directory too: a restored database works with new secrets, but
`auth_session_secret` signs the article links and sessions, so with a new
one every link handed out before (in a bookmark or a feed reader) stops
working.

## Backup

`pg_dump` runs inside the `db` container, so its version always matches the
server's. From the directory with `compose.yaml`:

```sh
docker compose exec -T db pg_dump -U brzask -Fc brzask > brzask-$(date +%F).dump
```

The custom format (`-Fc`) is compressed: a database of a few thousand
articles with their vectors is a few megabytes. A dump is consistent while
the API and the worker keep running.

A dump cut short (a full disk, a killed job) still looks like a file. Check
that it lists the tables before relying on it, or before rotating older
copies away:

```sh
docker compose exec -T db pg_restore -l < brzask-2026-10-21.dump | grep -c 'TABLE DATA'
```

A daily cron job or systemd timer running both commands, writing to a
temporary name and renaming on success, is enough.

## Restore

Stop the services that use the database, replace it, and start again:

```sh
docker compose stop api worker
docker compose exec -T db dropdb -U brzask brzask
docker compose exec -T db createdb -U brzask brzask
docker compose exec -T db pg_restore -U brzask -d brzask --no-owner < brzask-2026-10-21.dump
docker compose up -d
```

The dump includes the `vector` extension. `migrate` runs on `up` and brings
an older dump's schema up to the running version, so a dump can be restored
into a newer release (not into an older one).

## Moving to another machine

Copy `compose.yaml`, `.env`, the `secrets` directory and a dump, then on the
new machine:

```sh
docker compose up -d db     # creates an empty brzask database
docker compose exec -T db pg_restore -U brzask -d brzask --no-owner < brzask-2026-10-21.dump
docker compose up -d
```
