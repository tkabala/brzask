import json
from typing import Any

import httpx2
import openai
import pytest

from brzask.clients.llm import (
    InvalidJSONError,
    LLMClient,
    LLMError,
    parse_json,
)
from brzask.clients.retry import ATTEMPTS
from brzask.clients.usage import UsageMeter
from brzask.config.settings import LLMSettings


def answer(
    content: str | None, *, cost: float | None = None, model: str = "test/model"
) -> httpx2.Response:
    usage: dict[str, Any] = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    if cost is not None:
        usage["cost"] = cost
    return httpx2.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        },
    )


def error(status: int, headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"message": f"status {status}"}}, headers=headers)


class Fake:
    """An LLM API that replies with the queued responses, recording requests and sleeps."""

    def __init__(self, *responses: httpx2.Response | Exception, report_cost: bool = False) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.sleeps: list[float] = []
        transport = httpx2.MockTransport(self._handle)
        client = openai.OpenAI(
            base_url="https://llm.test/v1",
            api_key="key",
            max_retries=0,
            http_client=httpx2.Client(transport=transport),
        )
        self.llm = LLMClient(
            client, "test/model", report_cost=report_cost, sleep=self.sleeps.append
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


# --- parse_json ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"ranking": [3, 1]}', {"ranking": [3, 1]}),
        ('```json\n{"ranking": [3, 1]}\n```', {"ranking": [3, 1]}),
        ("```\n[1, 2]\n```", [1, 2]),
        ('Here is the ranking:\n{"ranking": [2]}', {"ranking": [2]}),
        ('{"ranking": [2]}\nLet me know if you need more.', {"ranking": [2]}),
        ('{"title": "a {curly} title"} trailing }', {"title": "a {curly} title"}),
        ('not {json} but then {"ok": true}', {"ok": True}),
        ('  \n {"a": 1}  ', {"a": 1}),
    ],
)
def test_parse_json_tolerates_wrapping(content: str, expected: Any) -> None:
    assert parse_json(content) == expected


@pytest.mark.parametrize("content", ["", "no json here", "{broken", "```json\n{broken\n```"])
def test_parse_json_rejects_answers_without_json(content: str) -> None:
    with pytest.raises(InvalidJSONError) as raised:
        parse_json(content)

    assert raised.value.content == content


# --- Requests and accounting ---------------------------------------------------


def test_complete_sends_the_prompt_and_records_usage() -> None:
    fake = Fake(answer("Hello", cost=0.00042, model="test/model-2026"))
    meter = UsageMeter()

    completion = fake.llm.complete("Rank these", purpose="ranking", system="Be brief", meter=meter)

    assert completion.content == "Hello"
    [request] = fake.requests
    assert request["model"] == "test/model"
    assert request["messages"] == [
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": "Rank these"},
    ]
    assert "response_format" not in request
    assert "usage" not in request
    usage = completion.usage
    assert (
        usage.model,
        usage.purpose,
        usage.input_tokens,
        usage.output_tokens,
        usage.cost_usd,
    ) == (
        "test/model-2026",
        "ranking",
        120,
        30,
        0.00042,
    )
    assert meter.calls == [usage]


def test_json_mode_and_cost_reporting_are_requested() -> None:
    fake = Fake(answer('{"ranking": [1]}'), report_cost=True)

    value, completion = fake.llm.complete_json("Rank", purpose="ranking")

    assert value == {"ranking": [1]}
    assert completion.usage.cost_usd is None
    [request] = fake.requests
    assert request["response_format"] == {"type": "json_object"}
    assert request["usage"] == {"include": True}
    assert [m["role"] for m in request["messages"]] == ["user"]


def test_complete_json_keeps_the_answer_when_it_is_not_json() -> None:
    fake = Fake(answer("I cannot rank these."))
    meter = UsageMeter()

    with pytest.raises(InvalidJSONError) as raised:
        fake.llm.complete_json("Rank", purpose="ranking", meter=meter)

    assert raised.value.content == "I cannot rank these."
    assert len(meter.calls) == 1  # the call was paid for, so it is counted


# --- Retries -------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        error(500),
        error(503),
        error(429),
        answer(None),
        answer("   "),
        httpx2.ConnectError("connection refused"),
        httpx2.ReadTimeout("timed out"),
    ],
    ids=["500", "503", "429", "no-content", "blank", "connect", "timeout"],
)
def test_temporary_failures_are_retried(failure: httpx2.Response | Exception) -> None:
    fake = Fake(failure, answer("ok"))

    assert fake.llm.complete("p", purpose="test").content == "ok"
    assert len(fake.requests) == 2
    assert len(fake.sleeps) == 1
    assert 1.6 <= fake.sleeps[0] <= 2.4  # first backoff step with jitter


def test_backoff_doubles_and_gives_up() -> None:
    fake = Fake(*[error(502) for _ in range(ATTEMPTS)])
    meter = UsageMeter()

    with pytest.raises(LLMError, match=f"ranking: gave up after {ATTEMPTS} attempts"):
        fake.llm.complete("p", purpose="ranking", meter=meter)

    assert len(fake.requests) == ATTEMPTS
    for delay, base in zip(fake.sleeps, [2.0, 4.0, 8.0], strict=True):
        assert 0.8 * base <= delay <= 1.2 * base
    assert meter.calls == []


def test_retry_after_is_respected_and_capped() -> None:
    fake = Fake(
        error(429, {"retry-after": "5"}),
        error(429, {"retry-after": "600"}),
        error(429, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        answer("ok"),
    )

    fake.llm.complete("p", purpose="test")

    assert fake.sleeps[:2] == [5.0, 30.0]
    assert 6.4 <= fake.sleeps[2] <= 9.6  # an HTTP date falls back to backoff


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    fake = Fake(error(status))

    with pytest.raises(LLMError, match="selection"):
        fake.llm.complete("p", purpose="selection")

    assert len(fake.requests) == 1
    assert fake.sleeps == []


def test_an_error_body_with_status_200_is_retried_and_reported() -> None:
    body = {"error": {"message": "upstream provider failed", "code": 502}}
    fake = Fake(*[httpx2.Response(200, json=body) for _ in range(ATTEMPTS)])

    with pytest.raises(LLMError, match="upstream provider failed"):
        fake.llm.complete("p", purpose="test")

    assert len(fake.requests) == ATTEMPTS


# --- Settings ------------------------------------------------------------------


def settings(**values: Any) -> LLMSettings:
    return LLMSettings.model_validate(values)


def test_from_settings_asks_openrouter_for_costs_only() -> None:
    openrouter = LLMClient.from_settings(settings())
    local = LLMClient.from_settings(settings(base_url="http://localhost:11434/v1", model="qwen3"))

    assert openrouter.report_cost
    assert not local.report_cost
    assert local.model == "qwen3"
    assert str(local.client.base_url) == "http://localhost:11434/v1/"
    assert local.client.api_key == "unused"
    assert local.client.max_retries == 0


def test_from_settings_uses_the_key_and_timeout() -> None:
    llm = LLMClient.from_settings(settings(api_key="sk-test", timeout_seconds=12))

    assert llm.client.api_key == "sk-test"
    assert llm.client.timeout == 12
