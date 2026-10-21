# Providers

brzask talks to models through three OpenAI-compatible APIs, each with its
own `*_BASE_URL`, `*_MODEL` and `*_API_KEY`:

| Role | Settings | Used for | Default |
|---|---|---|---|
| Chat model | `LLM_*` | Ranking the pool, writing the digest; with `WEB_SEARCH=llm-online`, web search | `deepseek/deepseek-v4-flash` on OpenRouter |
| Embeddings | `EMBEDDING_*` | Deduplication and search | `google/gemini-embedding-001` on OpenRouter |
| Judge | `JUDGE_*` | Same-day duplicates, discovery, composite ranking | `typesafe/jev-1.13` (System One) on OpenRouter |

The embedding and judge settings fall back to the chat model's URL and key,
so one provider needs one key. Every setting is listed in
[Configuration](configuration.md).

Two requirements hold for any provider:

- **Long prompts.** The ranking prompt lists the whole pool: about 16,000
  input tokens, and a reasoning model writes another 8,000 before it answers.
  The model needs a context of 32,000 tokens or more.
- **768-dimension embeddings.** brzask asks for 768 dimensions and checks
  every vector it gets. A provider that ignores the request fails the run
  with `expected 768 dimensions`; choose a model that returns 768 or can be
  shortened to it.

## OpenRouter

The default. One [OpenRouter](https://openrouter.ai) key covers ranking,
embeddings, the judge and web search with `llm-online`:

```sh
# .env
LLM_API_KEY=sk-or-...           # or the llm_api_key file from `brzask setup`
WEB_SEARCH=llm-online           # optional: source discovery through perplexity/sonar
```

A daily digest costs about half a cent with the defaults (ranking $0.003,
selection $0.002, embeddings $0.001, measured on a 200-article pool). On
OpenRouter, brzask asks for each call's cost and records it in the run's
statistics, shown on the Status page.

## Ollama

For a fully local setup, run [Ollama](https://ollama.com) and point every
URL at it. There is no System One model locally, so the chat model judges
(`JUDGE_BACKEND=llm`), and web search goes through SearXNG (the `search`
profile, see [Installation](install.md#optional-services)):

```sh
# .env
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=qwen3:14b
LLM_API_KEY=
EMBEDDING_MODEL=nomic-embed-text
JUDGE_BACKEND=llm
WEB_SEARCH=searxng
COMPOSE_PROFILES=search
```

Use whatever host name reaches Ollama from the containers:
`http://host.docker.internal:11434/v1` for Ollama on the host (with
`extra_hosts: ["host.docker.internal:host-gateway"]` on Linux), or the
service name when it runs in the same compose project. Pull the models
first (`ollama pull nomic-embed-text`).

Things to know:

- **Context length.** Ollama cuts prompts to its context length without an
  error. Start the server with `OLLAMA_CONTEXT_LENGTH=32768` or more, or the
  ranking sees only the start of the pool.
- **Embeddings.** `nomic-embed-text` returns 768 dimensions, and brzask adds
  the `search_query:` and `search_document:` prefixes it expects (`e5`
  models get `query:` and `passage:`). The deduplication thresholds were
  measured on `gemini-embedding-001`; for another model brzask uses them with
  a warning on every run. Check them with `brzask replay` before relying on
  them (see [Measuring changes](measuring.md#embedding-models-reembed-and-replay)).
- **Speed.** A ranking call is a long prompt and a long answer; on a CPU it
  can take many minutes. Raise `LLM_TIMEOUT_SECONDS` if calls time out.
- **Quality.** The ranking and the selection were measured with
  `deepseek/deepseek-v4-flash`. A small local model follows the JSON format,
  but ranks less well; compare it with `brzask replay` and `llm_model` in a
  replay configuration.

## Gemini

Gemini models are available through OpenRouter, which is how the default
embedding model is used. To call Google directly, use its OpenAI-compatible
endpoint with a key from [Google AI Studio](https://aistudio.google.com):

```sh
# .env
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-2.5-flash
LLM_API_KEY=...                 # the Gemini API key
EMBEDDING_MODEL=gemini-embedding-001
JUDGE_BACKEND=llm               # or keep System One with JUDGE_BASE_URL and JUDGE_API_KEY for OpenRouter
```

!!! warning "Not yet tested directly"
    Calling Google's endpoint directly has not been tested with brzask.
    The embeddings must come back with 768 dimensions; if the endpoint
    ignores the request, the digest stops with `expected 768 dimensions`.
    Use the embeddings through OpenRouter then:
    `EMBEDDING_BASE_URL=https://openrouter.ai/api/v1`,
    `EMBEDDING_MODEL=google/gemini-embedding-001` and an
    `EMBEDDING_API_KEY`.

The vectors are the same model either way, so the measured deduplication
thresholds apply.

## Other providers

Any server with OpenAI-compatible `/chat/completions` (with JSON output) and
`/embeddings` works: vLLM, llama.cpp's server, LM Studio, OpenAI, and others.
Set the three URLs, models and keys, and `JUDGE_BACKEND=llm` unless the
provider serves a System One model. When the embedding model changes on an
instance that already has history, move the stored vectors with
`brzask reembed` (see [ADR 0022](decisions/0022-one-embedding-model-at-a-time-with-thresholds-per-model.md)).
