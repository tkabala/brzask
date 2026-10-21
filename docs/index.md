# brzask

brzask is a self-hosted daily news digest. Every day it reads around 200 articles from your RSS and Atom sources and picks exactly 7 worth reading. It learns from what you open, and its source list maintains itself.

To try it, follow the [quickstart](install.md#quickstart): three commands
with Docker Compose.

## Documentation

Running brzask:

- [Installation](install.md): Docker Compose, optional services, images and commands.
- [Configuration](configuration.md): every setting with its default.
- [Providers](providers.md): OpenRouter, Ollama, Gemini and other OpenAI-compatible APIs.
- [Reverse proxy](reverse-proxy.md): TLS in front, trusted proxies and single sign-on.
- [Backup and restore](backup.md): `pg_dump`, restore and moving to another machine.

How it works:

- [Architecture](architecture.md): the system, its containers and the daily digest.
- [Data model](data-model.md): tables, states and why they exist.
- [Measuring changes](measuring.md): how changes to limits, prompts, models and extractors are judged.
- [Architecture decisions](decisions/index.md): why brzask is built the way it is.

Development:

- [HTTP API](api.md): authentication, endpoints and errors.
- [Frontend](frontend.md): the web app, its client and its tests.
