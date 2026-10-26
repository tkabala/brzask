"""Chat completions over any OpenAI-compatible API (OpenRouter, Ollama, OpenAI, ...)."""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlsplit

import openai
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from brzask.clients.retry import APIError, EmptyResponseError, call_with_retries
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.config.settings import LLMSettings
from brzask.log import get_logger
from brzask.telemetry import api_call_span

log = get_logger(__name__)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```", re.DOTALL)


class LLMError(APIError):
    """The chat API failed or kept failing; the message says why."""


class InvalidJSONError(LLMError):
    """The model answered, but not with JSON. `content` keeps the answer for the logs."""

    def __init__(self, content: str) -> None:
        super().__init__(f"model did not return JSON: {content[:200]!r}")
        self.content = content


@dataclass(frozen=True, slots=True)
class Completion:
    content: str
    usage: CallUsage


def parse_json(content: str) -> Any:
    """The first JSON value in a model answer.

    Models wrap JSON in code fences or add a sentence before or after it, even
    in JSON mode; both are tolerated. Raises `InvalidJSONError` otherwise.
    """
    text = content.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char in "{[":
            try:
                value, _ = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                continue
            return value
    raise InvalidJSONError(content)


class LLMClient:
    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        report_cost: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model
        self.report_cost = report_cost
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> Self:
        api_key = settings.api_key.get_secret_value() if settings.api_key else None
        client = openai.OpenAI(
            base_url=str(settings.base_url),
            # Local servers need no key, but the SDK requires one.
            api_key=api_key or "unused",
            timeout=settings.timeout_seconds,
            max_retries=0,  # retried here, with a log line per retry
        )
        # OpenRouter reports the cost of a call only when asked; other APIs reject the field.
        is_openrouter = urlsplit(str(settings.base_url)).hostname == "openrouter.ai"
        return cls(client, settings.model, report_cost=is_openrouter)

    def complete(
        self,
        prompt: str,
        *,
        purpose: str,
        system: str | None = None,
        json_mode: bool = False,
        meter: UsageMeter | None = None,
    ) -> Completion:
        """Send one prompt and return the answer; retries temporary failures."""
        messages: list[ChatCompletionMessageParam] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        def attempt() -> tuple[str, CallUsage, dict[str, Any]]:
            started = time.perf_counter()
            response = self._create(messages, json_mode=json_mode)
            content = _content(response)
            usage = _usage(response, self.model, purpose, started)
            return content, usage, _call_details(response, content)

        with api_call_span("chat", self.model, purpose) as span:
            content, usage, details = call_with_retries(
                attempt, purpose=purpose, error=LLMError, sleep=self._sleep
            )
            span.record(usage)
        if meter is not None:
            meter.add(usage)
        log.info(
            "llm call",
            purpose=purpose,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
            **details,
        )
        return Completion(content, usage)

    def complete_json(
        self,
        prompt: str,
        *,
        purpose: str,
        system: str | None = None,
        meter: UsageMeter | None = None,
    ) -> tuple[Any, Completion]:
        """Like `complete` in JSON mode, returning the parsed value and the raw completion."""
        completion = self.complete(
            prompt, purpose=purpose, system=system, json_mode=True, meter=meter
        )
        return parse_json(completion.content), completion

    def _create(
        self, messages: list[ChatCompletionMessageParam], *, json_mode: bool
    ) -> ChatCompletion:
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"} if json_mode else openai.omit,
            extra_body={"usage": {"include": True}} if self.report_cost else None,
        )


def _content(response: ChatCompletion) -> str:
    # `choices` is required by the schema, but some providers send an error object instead.
    choices = response.choices or []
    content = choices[0].message.content if choices else None
    if not content or not content.strip():
        error = (response.model_extra or {}).get("error")
        raise EmptyResponseError(f"empty answer{f': {error}' if error else ''}")
    return content


def _call_details(response: ChatCompletion, content: str) -> dict[str, Any]:
    """Who served the call and how much of its output was reasoning, for the log.

    With the same model and nearly the same prompt, a day's ranking took 3.5k
    or 22.6k output tokens (and 42 s or 141 s); the answer's length tells
    reasoning apart from answer tokens when the provider does not report them.
    """
    # Read defensively: these only feed the log, and providers send odd shapes
    # that must not discard an answer already paid for.
    tokens = getattr(response.usage, "completion_tokens_details", None)
    reasoning = getattr(tokens, "reasoning_tokens", None)
    provider = (response.model_extra or {}).get("provider")
    return {
        "provider": provider if isinstance(provider, str) else None,
        "reasoning_tokens": reasoning if isinstance(reasoning, int) else None,
        "answer_chars": len(content),
    }


def _usage(response: ChatCompletion, model: str, purpose: str, started: float) -> CallUsage:
    usage = response.usage
    cost = (usage.model_extra or {}).get("cost") if usage else None
    return CallUsage(
        model=response.model or model,
        purpose=purpose,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
