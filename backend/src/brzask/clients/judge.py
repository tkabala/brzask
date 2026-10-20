"""Judgements: typed questions about a piece of state, answered with probabilities.

A question is a `Noul` (the probability that a statement holds), a `Choice`
(one option of a set) or a `Score` (a position on ordered levels). Questions
about the same state go in one call and are answered independently of each
other. Two backends answer them with the same answer types:

- `SystemOneJudge`: a System One model (TypeSafe's Jev, Liquid's d1) through
  the `/systemone` endpoint of OpenRouter or of the model's own API;
- `LLMJudge`: any chat model, asked for the same probabilities in JSON (works
  with local servers such as Ollama).

Confidence follows the System One definitions, so code can threshold it the
same way whichever backend answered.
"""

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, Self

import openai

from brzask import prompts
from brzask.clients.llm import LLMClient, LLMError
from brzask.clients.retry import APIError, EmptyResponseError, call_with_retries
from brzask.clients.usage import CallUsage, UsageMeter
from brzask.config.settings import Settings
from brzask.log import get_logger
from brzask.telemetry import api_call_span

log = get_logger(__name__)

# A versioned ID, not `jev-latest`: aliases point to different versions on
# OpenRouter and on TypeSafe's own API, and move when a version ships.
DEFAULT_SYSTEM_ONE_MODEL = "typesafe/jev-1.13"
# Answers take well under a second; a request with a long state takes longer.
REQUEST_TIMEOUT_SECONDS = 60.0

type Text = str | Mapping[str, Any] | Sequence[Any]
"""State, instructions and criteria: plain text, or JSON when the parts need names."""


class JudgeError(APIError):
    """The judge failed, or answered something that does not fit the questions."""


@dataclass(frozen=True, slots=True)
class Noul:
    """Does a statement hold? `true` and `false` optionally say what counts as each."""

    instructions: Text
    true: Text | None = None
    false: Text | None = None


@dataclass(frozen=True, slots=True)
class Choice:
    """Which one of the options (name: meaning) fits?"""

    instructions: Text
    options: Mapping[str, Text]

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError("a Choice needs at least 2 options")


@dataclass(frozen=True, slots=True)
class Score:
    """Where on the levels (lowest first) does the state sit?"""

    instructions: Text
    levels: Sequence[Text]

    def __post_init__(self) -> None:
        # d1 rejects a single level; Jev answers it, but it says nothing.
        if len(self.levels) < 2:
            raise ValueError("a Score needs at least 2 levels")


type Question = Noul | Choice | Score


@dataclass(frozen=True, slots=True)
class NoulAnswer:
    probability: float  # of yes; 0.5 means undecided, not "somewhat"


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float  # 1 = all probability on one option, 0 = spread evenly


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    score: float  # probability-weighted level, 0 = the first level
    probabilities: tuple[float, ...]  # one per level
    confidence: float  # 1 = all on one level; lower the further probability sits from it


type Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True, slots=True)
class Judgement:
    """The answers of one call, by question name."""

    answers: Mapping[str, Answer]
    usage: CallUsage = field(repr=False)

    def noul(self, name: str) -> NoulAnswer:
        return self._answer(name, NoulAnswer)

    def choice(self, name: str) -> ChoiceAnswer:
        return self._answer(name, ChoiceAnswer)

    def score(self, name: str) -> ScoreAnswer:
        return self._answer(name, ScoreAnswer)

    def _answer[A: Answer](self, name: str, kind: type[A]) -> A:
        answer = self.answers[name]
        if not isinstance(answer, kind):
            raise TypeError(f"{name!r} is a {type(answer).__name__}, not a {kind.__name__}")
        return answer


class Judge(Protocol):
    model: str

    def ask(
        self,
        state: Text,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        """Answer every question about `state`; names are for code and never sent as meaning."""
        ...

    def close(self) -> None:
        """Close the judge's client."""


def choice_confidence(probabilities: Sequence[float]) -> float:
    """How far the top option stands out: 1 when it has everything, 0 when all are even."""
    count = len(probabilities)
    return _clamp((count * max(probabilities) - 1) / (count - 1))


def score_confidence(probabilities: Sequence[float]) -> float:
    """How close the probability sits to the most likely level, against an even spread.

    Probability one level away lowers it less than probability three levels away.
    """
    count = len(probabilities)
    peak = max(range(count), key=lambda level: probabilities[level])
    spread = sum(p * abs(level - peak) for level, p in enumerate(probabilities))
    even = sum(abs(level - (count - 1) / 2) for level in range(count)) / count
    return _clamp(1 - spread / even)


def build_judge(settings: Settings, model: str | None = None) -> Judge:
    """The judge configured by `JUDGE_BACKEND`; `model` replaces JUDGE_MODEL."""
    if settings.judge.backend == "system-one":
        return SystemOneJudge.from_settings(settings, model)
    return LLMJudge.from_settings(settings, model)


# --- System One ------------------------------------------------------------------


class SystemOneJudge:
    """A System One model through `POST {base_url}/systemone`.

    The base URL ends with the API version, like LLM_BASE_URL:
    `https://openrouter.ai/api/v1` or `https://api.typesafe.ai/v1`.
    """

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings, model: str | None = None) -> Self:
        judge, llm = settings.judge, settings.llm
        secret = judge.api_key or llm.api_key
        # The OpenAI SDK sends the request: same errors, retries and tracing as the LLM.
        client = openai.OpenAI(
            base_url=str(judge.base_url or llm.base_url),
            api_key=secret.get_secret_value() if secret else "unused",
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,  # retried here, with a log line per retry
        )
        return cls(client, model or judge.model or DEFAULT_SYSTEM_ONE_MODEL)

    def close(self) -> None:
        self.client.close()

    def ask(
        self,
        state: Text,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        if not questions:
            raise ValueError("ask at least one question")
        body = {
            "model": self.model,
            "state": state,
            "questions": {name: _wire_question(question) for name, question in questions.items()},
        }

        def attempt() -> tuple[dict[str, Any], int]:
            started = time.perf_counter()
            data = self.client.post("/systemone", cast_to=object, body=body)
            if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                error = data.get("error") if isinstance(data, dict) else None
                raise EmptyResponseError(f"no answers{f': {error}' if error else ''}")
            return data, round((time.perf_counter() - started) * 1000)

        with api_call_span("systemone", self.model, purpose) as span:
            data, duration_ms = call_with_retries(
                attempt, purpose=purpose, error=JudgeError, sleep=self._sleep
            )
            usage = _system_one_usage(data, self.model, purpose, duration_ms)
            span.record(usage)
        if meter is not None:
            meter.add(usage)
        log.info(
            "judge call",
            purpose=purpose,
            model=usage.model,
            questions=len(questions),
            input_tokens=usage.input_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
        )
        raw = data["answers"]
        answers = {
            name: _checked(purpose, name, _system_one_answer, question, raw.get(name))
            for name, question in questions.items()
        }
        return Judgement(answers, usage)


def _wire_question(question: Question) -> dict[str, Any]:
    match question:
        case Noul(instructions, true, false):
            wire: dict[str, Any] = {"type": "noul", "instructions": instructions}
            criteria = {
                key: value for key, value in (("true", true), ("false", false)) if value is not None
            }
            if criteria:
                wire["criteria"] = criteria
            return wire
        case Choice(instructions, options):
            return {"type": "choice", "instructions": instructions, "criteria": dict(options)}
        case Score(instructions, levels):
            return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def _system_one_answer(question: Question, raw: object) -> Answer:
    if not isinstance(raw, dict):
        raise ValueError("missing")
    expected = {Noul: "noul", Choice: "choice", Score: "score"}[type(question)]
    if raw.get("type") != expected:
        raise ValueError(f"expected a {expected}, got {raw.get('type')!r}")
    match question:
        case Noul():
            return NoulAnswer(_probability(raw.get("noul")))
        case Choice(_, options):
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict) or set(probabilities) != set(options):
                raise ValueError("probabilities do not match the options")
            choice = raw.get("choice")
            if choice not in options:
                raise ValueError(f"unknown option {choice!r}")
            return ChoiceAnswer(
                choice=str(choice),
                probabilities={name: _probability(probabilities[name]) for name in options},
                confidence=_probability(raw.get("confidence")),
            )
        case Score(_, levels):
            probabilities = raw.get("probabilities")
            keys = [str(level) for level in range(len(levels))]
            if not isinstance(probabilities, dict) or set(probabilities) != set(keys):
                raise ValueError("probabilities do not match the levels")
            score = _number(raw.get("score"))
            if not 0 <= score <= len(levels) - 1:
                raise ValueError(f"score {score} is outside the levels")
            return ScoreAnswer(
                score=score,
                probabilities=tuple(_probability(probabilities[key]) for key in keys),
                confidence=_probability(raw.get("confidence")),
            )


def _system_one_usage(
    data: dict[str, Any], model: str, purpose: str, duration_ms: int
) -> CallUsage:
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cost = usage.get("cost")  # OpenRouter adds it; TypeSafe's own API does not
    served = data.get("model")
    return CallUsage(
        model=served if isinstance(served, str) and served else model,
        purpose=purpose,
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_ms=duration_ms,
    )


# --- Chat model ----------------------------------------------------------------------


class LLMJudge:
    """A chat model asked for the probabilities in JSON; answers are built in code."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.model = llm.model

    @classmethod
    def from_settings(cls, settings: Settings, model: str | None = None) -> Self:
        judge, llm = settings.judge, settings.llm
        overrides = {
            key: value
            for key, value in (
                ("model", model or judge.model),
                ("base_url", judge.base_url),
                ("api_key", judge.api_key),
            )
            if value is not None
        }
        return cls(LLMClient.from_settings(llm.model_copy(update=overrides)))

    def close(self) -> None:
        self.llm.client.close()

    def ask(
        self,
        state: Text,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        meter: UsageMeter | None = None,
    ) -> Judgement:
        if not questions:
            raise ValueError("ask at least one question")
        prompt = prompts.render(
            "judge",
            state=_json_text(state),
            questions=[_prompt_question(name, question) for name, question in questions.items()],
        )
        try:
            value, completion = self.llm.complete_json(prompt, purpose=purpose, meter=meter)
        except LLMError as error:
            raise JudgeError(str(error)) from error
        raw = value.get("answers") if isinstance(value, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        answers = {
            name: _checked(purpose, name, _llm_answer, question, raw.get(name))
            for name, question in questions.items()
        }
        return Judgement(answers, completion.usage)


def _prompt_question(name: str, question: Question) -> dict[str, Any]:
    match question:
        case Noul(instructions, true, false):
            criteria = {
                key: value for key, value in (("true", true), ("false", false)) if value is not None
            }
            return {
                "name": name,
                "kind": "noul",
                "instructions": _json_text(instructions),
                "criteria": _json_text(criteria) if criteria else None,
                "options": [],
            }
        case Choice(instructions, options):
            return {
                "name": name,
                "kind": "choice",
                "instructions": _json_text(instructions),
                "criteria": _json_text(dict(options)),
                "options": list(options),
            }
        case Score(instructions, levels):
            return {
                "name": name,
                "kind": "score",
                "instructions": _json_text(instructions),
                "criteria": _json_text(list(levels)),
                "options": [str(level) for level in range(len(levels))],
            }


def _llm_answer(question: Question, raw: object) -> Answer:
    if not isinstance(raw, dict):
        raise ValueError("missing")
    match question:
        case Noul():
            return NoulAnswer(_clamp(_number(raw.get("probability"))))
        case Choice(_, options):
            probabilities = _distribution(raw.get("probabilities"), list(options))
            return ChoiceAnswer(
                # The first of equally likely options, in the order they were asked.
                choice=max(options, key=lambda name: probabilities[name]),
                probabilities=probabilities,
                confidence=choice_confidence(list(probabilities.values())),
            )
        case Score(_, levels):
            keys = [str(level) for level in range(len(levels))]
            distribution = _distribution(raw.get("probabilities"), keys)
            per_level = tuple(distribution[key] for key in keys)
            return ScoreAnswer(
                score=sum(level * p for level, p in enumerate(per_level)),
                probabilities=per_level,
                confidence=score_confidence(per_level),
            )


def _distribution(raw: object, keys: list[str]) -> dict[str, float]:
    """Probabilities for `keys` scaled to sum to 1; a key the model left out gets 0."""
    if not isinstance(raw, dict):
        raise ValueError("probabilities missing")
    values = {key: max(0.0, _number(raw.get(key, 0))) for key in keys}
    total = sum(values.values())
    if total <= 0:
        raise ValueError("all probabilities are 0")
    return {key: value / total for key, value in values.items()}


# --- Shared ------------------------------------------------------------------------


def _checked(
    purpose: str,
    name: str,
    parse: Callable[[Question, object], Answer],
    question: Question,
    raw: object,
) -> Answer:
    try:
        return parse(question, raw)
    except ValueError as error:
        raise JudgeError(f"{purpose}: unusable answer to {name!r}: {error}") from error


def _json_text(value: Text) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"expected a number, got {value!r}")
    return float(value)


def _probability(value: object) -> float:
    number = _number(value)
    if not 0 <= number <= 1:
        raise ValueError(f"{number} is not a probability")
    return number


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
