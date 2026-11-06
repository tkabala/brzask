# Backup and restore

Everything brzask knows lives in Postgres: sources, interests, articles with
their embeddings, digests, opens, runs and the change log. Keep the `secrets`
directory too: a restored database works with new secrets, but
`auth_session_secret` signs the article links and sessions, so with a new
one every link handed out before (in a bookmark or a feed reader) stops
working.

There are two ways to copy it:

- **`pg_dump`**: the whole database, fast to take and to restore into the same
  setup. The everyday backup.
- **`brzask export`**: a [portable archive](#portable-export) of the same data
  that does not depend on the Postgres version, pgvector or the brzask release
  it came from. For moving to another Postgres major or machine, and for a
  copy you can still read in a few years.

Whichever you keep, [test that it restores](#test-a-restore) now and then.

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

## Portable export

`brzask export` writes every source, interest, article with its vectors,
run, setting, change-log entry and API token (their hashes) to one gzip'd
[JSON Lines](https://jsonlines.org/) file. Like a dump, it is one consistent
snapshot while the API and the worker keep running:

```sh
docker compose exec -T api brzask export - > brzask-$(date +%F).jsonl.gz
```

`-` writes to standard output, so the file lands on the host (the container
has nowhere to keep it). Counts per table go to standard error. Run outside a
container, `brzask export` without `-` writes `brzask-<date>.jsonl.gz` in the
current directory.

The first line names the format and the schema revision, each following line
is one row (`{"table": "sources", "row": {...}}`), and the last line counts
the rows per table. A file cut short has no last line, so `brzask import`
refuses it. To look inside:

```sh
zcat brzask-2026-11-06.jsonl.gz | head -1
zcat brzask-2026-11-06.jsonl.gz | jq -c 'select(.table == "interests") | .row'
```

Login sessions are not in an archive: after a restore, everyone signs in
again. Feed and API tokens keep working.

## Restore from an archive

`brzask import` loads an archive into an empty database at the latest
migration, in one transaction: either everything is restored or nothing is.
It refuses a database that already has data, a damaged or incomplete file,
and an archive from a newer brzask than the one running (an older one is
fine). To replace an instance:

```sh
docker compose stop api worker
docker compose exec -T db dropdb -U brzask brzask
docker compose exec -T db createdb -U brzask brzask
docker compose run --rm migrate
docker compose run --rm -T migrate import - < brzask-2026-11-06.jsonl.gz
docker compose up -d
```

On a new machine, copy `compose.yaml`, `.env` and the `secrets` directory,
then run the last three commands.

## Test a restore

A backup counts once it has been restored. Restore it into a scratch database
next to the live one, compare, and drop it; the running instance is not
touched:

=== "Archive"

    ```sh
    docker compose exec -T db createdb -U brzask brzask_restore_test
    docker compose run --rm -e DB_NAME=brzask_restore_test migrate
    docker compose run --rm -T -e DB_NAME=brzask_restore_test migrate import - < brzask-2026-11-06.jsonl.gz
    ```

    `import` prints the rows it loaded per table, the same counts as the
    archive's last line (`zcat brzask-2026-11-06.jsonl.gz | tail -1`).

=== "pg_dump"

    ```sh
    docker compose exec -T db createdb -U brzask brzask_restore_test
    docker compose exec -T db pg_restore -U brzask -d brzask_restore_test --no-owner < brzask-2026-10-21.dump
    docker compose run --rm -e DB_NAME=brzask_restore_test migrate
    ```

Then look at it as brzask sees it, and compare with the live instance:

```sh
docker compose run --rm -e DB_NAME=brzask_restore_test migrate status
docker compose exec api brzask status
docker compose exec -T db dropdb -U brzask brzask_restore_test
```

`status` counts articles (stored, shown, opened), sources by status and
stored vectors, and names the last digest and each pipeline's last run; a
restore of last night's backup matches the live instance up to what came in
since. Doing this after every upgrade, and now and then from the
backup copies themselves, is what tells you they are usable.
