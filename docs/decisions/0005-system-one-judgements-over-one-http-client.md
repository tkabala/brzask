---
status: accepted
date: 2026-10-20
---

# System One judgements over one HTTP client for every model

## Context and problem statement

Some of brzask's decisions are narrow judgements: is this pair of articles the
same event, how well does an article fit an interest, is a page mostly
promotion. System One models answer such questions as typed values with
probabilities (`noul`: probability of yes; `choice`: one option of a set;
`score`: a position on ordered levels) instead of generated text. Two such
models are available through OpenRouter: TypeSafe's Jev and Liquid's d1. Can
one client serve both, and how should brzask talk to them?

## Decision drivers

- One API key (OpenRouter) covers the LLM, embeddings and judgements by default.
- The model is a setting; switching between Jev and d1 must not change code.
- Answers must be reproducible enough to compare models with `brzask replay`.
- `mypy --strict` and few dependencies.

## Considered options

- A small client of brzask's own for `POST {base}/v1/systemone`, the request
  and response shapes typed in brzask, sent through the `openai` SDK's request
  layer that the LLM and embedding clients already use.
- The TypeSafe Python SDK (`typesafe_sdk`) pointed at OpenRouter.
- The OpenRouter Python SDK.

## Decision outcome

Chosen option: a client of brzask's own, because the API is one endpoint with a
stable shape that both models accept, and the SDKs add a dependency for one
call while each fits only one provider well.

### Evidence

Real calls on 2026-10-20 to `https://openrouter.ai/api/v1/systemone` with an
OpenRouter key, same request to each model: state = a reader interest with
notes and two or three articles (source, title, snippet), questions = one
`noul` (are two articles the same event), one `choice` (kind of article), one
`score` (fit to the interest, four levels); then a related-topic pair that is
not the same event, a `noul` without criteria, and invalid requests.

| | Jev 1.13 (`typesafe/jev-1.13`) | d1 (`liquid/d1`) |
|---|---|---|
| Same request shape | yes | yes |
| Served as | `typesafe/jev-1.13-20260917` | `liquid/d1-20260930` |
| Same event (true pair) | 0.98 | 0.9998 |
| Same event (related, different events) | 0.02 | 0.0003 |
| Kind of a release announcement | release, 1.00 | release, 0.998 |
| Interest fit (0–3) | 2.78 | 2.96 |
| Promotion score of a webinar invitation (0–2) | 2.00, confidence 1.00 | 1.68, confidence 0.51 |
| Price per million input tokens | $0.042 | $0.02 |
| Input tokens, first request | 717 | 418 |
| Cost, first request | $0.000030 | $0.0000084 |
| Latency, end to end | 0.26–0.41 s | 0.27 s |
| Context length | 262k (64k without the long-context header) | 65k |

Findings that shape the client:

- Answers: `noul` → `{"noul": p}`; `choice` → `choice`, `probabilities` per
  option, `confidence`; `score` → `score` (a probability-weighted float, levels
  numbered from 0), `legend` (level number → text), `probabilities`,
  `confidence`. Jev rounds probabilities to two decimals; d1 returns full
  floats, so equal answers from the two models do not compare equal as numbers.
- Instructions and criteria accept JSON objects as well as strings on both
  models; a `noul` without criteria works on both.
- Output tokens are free on both; Jev reports output tokens, d1 reports 0.
  OpenRouter adds `id`, `provider` and `usage.cost` to the response.
- Model names: bare names are mapped into the `typesafe/` namespace, so `d1`
  fails (`Model typesafe/d1 does not exist`); always send the author prefix.
  `jev-latest` on OpenRouter served Jev 1.14, while TypeSafe's own
  `jev-latest` points to 1.13: aliases differ between providers, so the
  setting takes a versioned ID and the response's `model` is recorded.
- Errors use OpenRouter's shape `{"error": {"message", "code"}}`, not
  TypeSafe's: schema errors (missing `criteria` on a `score`, unknown `type`,
  no questions) are 400 with the validation list as a JSON string in
  `message`; errors from the model provider are wrapped, e.g. d1 rejects a
  one-level `score` with 422 while Jev answers it; a bad key is 401.
- Neither model is listed by OpenRouter's `GET /api/v1/models`; they are
  reachable by `GET /api/v1/models/{author}/{slug}/endpoints` and by the
  System One endpoint. The TypeSafe SDK's model listing fails against
  OpenRouter for the same reason.

All calls together cost under $0.001.

### Consequences

- Good, because Jev and d1 are one setting apart, and another System One
  provider needs only a base URL and a key.
- Good, because the typed request and response live in brzask and are checked
  by `mypy --strict`.
- Good, because retries (429, 529 and other server errors, with
  `Retry-After`), timeouts and tracing are the ones every other API call
  already has.
- Bad, because `score` questions need at least two levels to work on every
  model; the client enforces that rather than relying on one provider's
  leniency.

## Pros and cons of the options

### Own client over the `openai` SDK's request layer

- Good, because no new dependency; the SDK's generic `post` sends any JSON
  body to the configured base URL and maps error statuses to the same
  exceptions as chat calls.
- Good, because errors from either provider map to brzask's own exceptions.
- Bad, because the shapes have to be kept up to date by hand.

### TypeSafe SDK

- Good, because typed questions, answers and retries come ready.
- Bad, because it is shaped around TypeSafe's own API (model listing, error
  shape) and d1 is not a TypeSafe model.

### OpenRouter SDK

- Good, because it covers System One, chat and embeddings.
- Bad, because brzask talks to any OpenAI-compatible endpoint through the
  `openai` SDK; the OpenRouter SDK would tie judgements to one provider.

## More information

Which model is the default, and whether judgements replace parts of the LLM
ranking and the deduplication thresholds, is decided by measuring with
`brzask replay`, not by this record. The confidence gap on the promotion
score (Jev 1.00, d1 0.51 on the same webinar invitation) is one example, not
a measurement; compare the models on stored history before choosing.

Until then the default is `typesafe/jev-1.13` (`JUDGE_MODEL`). Where no System
One model is reachable, `JUDGE_BACKEND=llm` asks the chat model the same
questions for probabilities in JSON and builds the same answers in code,
confidence included; a chat model's probabilities are not trained to be
calibrated, so thresholds measured with one backend do not carry over to the
other.
