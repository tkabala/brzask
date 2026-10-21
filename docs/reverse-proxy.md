# Reverse proxy

The compose file publishes the web app on `127.0.0.1:8000` only. To reach it
from other machines, put a reverse proxy with TLS in front. brzask must be
served at the root of its host name (`https://news.example.com/`), not under
a path.

## Caddy

```caddyfile
news.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## nginx

```nginx
server {
    listen 443 ssl;
    server_name news.example.com;
    # ssl_certificate and ssl_certificate_key as usual

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Trusting the proxy

brzask believes forwarding headers only from the addresses in
`TRUSTED_PROXIES`. It uses them for three things: the client address in the
login rate limit, whether the browser came over HTTPS (for the `Secure`
flag of the session cookie, with `AUTH_COOKIE_SECURE=auto`), and the user
name in header mode.

Behind Docker's published port, the API does not see the proxy's own
address but the gateway of the compose network. Find it with:

```sh
docker network inspect brzask_default --format '{{(index .IPAM.Config 0).Gateway}}'
```

and set it, for example `TRUSTED_PROXIES=172.20.0.1`. A proxy running as a
container in the same compose network is trusted by its subnet instead,
such as `172.20.0.0/16`. Without `TRUSTED_PROXIES`, everything still works
over plain HTTP; behind an HTTPS proxy set `AUTH_COOKIE_SECURE=true` instead
if you prefer not to trust any header.

## Single sign-on

With `AUTH_MODE=header`, brzask has no login of its own: an authenticating
proxy (Authelia, Authentik, oauth2-proxy, Tailscale Serve and the like) sets
the user name in a header, `Remote-User` by default (`AUTH_HEADER`). The
header is read only from `TRUSTED_PROXIES`, which header mode requires, so
make sure the proxy removes the header from what the browser sends.

```sh
# .env
AUTH_MODE=header
AUTH_HEADER=Remote-User
TRUSTED_PROXIES=172.20.0.1
```

Scripts and agents use API tokens in either mode (`brzask tokens create`,
then `Authorization: Bearer brz_...`).

`AUTH_MODE=none` turns authentication off. Use it only when the port is
reachable from nowhere but your own machine.
