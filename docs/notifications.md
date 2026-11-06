# Notifications

brzask can send two messages, through [Apprise](https://github.com/caronc/apprise)
to almost any service: ntfy, Telegram, Matrix, Signal, Discord, Slack, Gotify,
email and [about a hundred more](https://github.com/caronc/apprise/wiki).

## What is sent

**Digest ready**, once a day, when the digest is built:

```text
brzask: today's 7 are ready

1. A new release of the Linux kernel drops support for i486
2. Why the Postgres planner ignored the index
...
7. A short history of time zones

https://news.example.com/
```

The titles are the digest's, in `DIGEST_LANGUAGE`. The link at the end is
`BASE_URL`, shown only when it is set.

**Pipeline failed**, when a digest, review, visited or discovery run ends
with an error, whether the worker or `brzask run` started it:

```text
brzask: discovery run failed

RuntimeError: the search API answered 401
run 0b6f1c2e-6a59-4a0f-9a55-3c1e0f6a7d10
https://news.example.com/status
```

## What is never sent

Nothing else, by design. No message for:

- a run that was skipped (paused, already done today, another run in progress,
  over the spending limit);
- a dry run;
- a run interrupted by Ctrl-C or a shutdown;
- a second digest of the same day (`brzask run digest --force`);
- a digest with no articles;
- new or muted sources, single articles, or anything else.

The run itself never depends on a notification: when the service is down, the
worker logs `notification not sent` with the failed entry's place in
`NOTIFY_URLS` and its service (never the URL) and goes on.

## Set it up

Put one or more [Apprise URLs](https://github.com/caronc/apprise/wiki#notification-services)
in `NOTIFY_URLS` in `.env`, separated by spaces or commas. URLs carry tokens,
so, like every secret, they can also come from a file named by
`NOTIFY_URLS_FILE` (a Docker or Kubernetes secret).

=== "ntfy"

    ```sh
    NOTIFY_URLS=ntfys://ntfy.sh/brzask-<random words>
    ```

    Anyone who knows a public ntfy.sh topic's name can read it: pick a long
    random one, or use your own ntfy server (`ntfys://user:password@ntfy.example.com/brzask`).

=== "Telegram"

    ```sh
    NOTIFY_URLS=tgram://<bot token>/<chat id>
    ```

=== "Email"

    ```sh
    NOTIFY_URLS=mailtos://user:password@mail.example.com?to=me@example.com
    ```

=== "Apprise API"

    For a self-hosted [Apprise API](https://github.com/caronc/apprise-api)
    server that holds the real targets under a key:

    ```sh
    NOTIFY_URLS=apprises://apprise.example.com/brzask
    ```

Restart the stack and send a test message:

```console
$ docker compose up -d
$ docker compose exec worker brzask notify test
Test notification sent.
```

A URL Apprise does not know stops the worker at start with
`NOTIFY_URLS entry 2 is not a URL Apprise knows`: the position, never the
URL. Leave `NOTIFY_URLS` empty to turn notifications off.

## Privacy

The digest's titles, the run's error and your `BASE_URL` leave the server
for the service you chose. Nothing else does.
