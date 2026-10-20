import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx2
import openai
import pytest

from brzask.clients.judge import (
    DEFAULT_SYSTEM_ONE_MODEL,
    Choice,
    ChoiceAnswer,
    Judge,
    JudgeError,
    LLMJudge,
    Noul,
    NoulAnswer,
    Question,
    Score,
    SystemOneJudge,
    build_judge,
    choice_confidence,
    score_confidence,
)
from brzask.clients.llm import LLMClient
from brzask.clients.retry import ATTEMPTS
from brzask.clients.usage import UsageMeter
from brzask.config.settings import Settings

STATE = {
    "interest": {"name": "Postgres", "notes": "want: internals; skip: webinars"},
    "article_a": {"title": "PostgreSQL 18 Released!"},
    "article_b": {"title": "PostgreSQL 18 Officially Released With Async I/O"},
}

QUESTIONS: dict[str, Question] = {
    "same_event": Noul(
        "Do `article_a` and `article_b` describe the same event?",
        true="Both report the same release.",
        false="Different events, even on one topic.",
    ),
    "kind": Choice(
        "What kind of article is `article_a`?",
        {"release": "A new version", "analysis": "How something works", "news": "Anything else"},
    ),
    "fit": Score(
        {"task": "How well does `article_b` match `interest`?", "priority": "notes first"},
        ["Unrelated", "Related, not wanted", "Exactly what is wanted"],
    ),
}

# What the model "thinks"; each fake API encodes it in its own wire format.
SAME_EVENT = 0.9
KIND = {"release": 0.8, "analysis": 0.15, "news": 0.05}
FIT = (0.1, 0.2, 0.7)

Encoder = Callable[[Mapping[str, Question], str], dict[str, Any]]


def system_one_body(questions: Mapping[str, Question], model: str) -> dict[str, Any]:
    """A System One response as OpenRouter sends it."""
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        match question:
            case Noul():
                answers[name] = {"type": "noul", "noul": SAME_EVENT}
            case Choice():
                answers[name] = {
                    "type": "choice",
                    "choice": max(KIND, key=lambda option: KIND[option]),
                    "probabilities": KIND,
                    "confidence": choice_confidence(list(KIND.values())),
                }
            case Score(_, levels):
                answers[name] = {
                    "type": "score",
                    "score": sum(level * p for level, p in enumerate(FIT)),
                    "legend": {str(level): text for level, text in enumerate(levels)},
                    "probabilities": {str(level): p for level, p in enumerate(FIT)},
                    "confidence": score_confidence(FIT),
                }
    return {
        "id": "gen-dec-1",
        "model": f"{model}-20260917",
        "provider": "TypeSafe",
        "answers": answers,
        "usage": {"input_tokens": 700, "output_tokens": 70, "cost": 0.00003},
    }


def llm_body(questions: Mapping[str, Question], model: str) -> dict[str, Any]:
    """A chat completion whose content is the judge prompt's JSON answer."""
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        match question:
            case Noul():
                answers[name] = {"probability": SAME_EVENT}
            case Choice():
                answers[name] = {"probabilities": KIND}
            case Score():
                answers[name] = {"probabilities": {str(level): p for level, p in enumerate(FIT)}}
    return chat({"answers": answers}, model)


def chat(content: object, model: str) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(content)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 700, "completion_tokens": 70, "total_tokens": 770},
    }


class FakeAPI:
    """Replies with queued responses; a callable builds a 200 body from the asked questions."""

    def __init__(self, *responses: httpx2.Response | Encoder) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []
        self.sleeps: list[float] = []
        self.questions: Mapping[str, Question] = QUESTIONS
        self.client = openai.OpenAI(
            base_url="https://judge.test/v1",
            api_key="key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self._handle)),
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, httpx2.Response):
            return response
        return httpx2.Response(200, json=response(self.questions, "test/model"))

    def body(self, index: int = -1) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[index].content)
        return body


def system_one(*responses: httpx2.Response | Encoder) -> tuple[Judge, FakeAPI]:
    api = FakeAPI(*responses)
    return SystemOneJudge(api.client, "test/model", sleep=api.sleeps.append), api


def llm(*responses: httpx2.Response | Encoder) -> tuple[Judge, FakeAPI]:
    api = FakeAPI(*responses)
    return LLMJudge(LLMClient(api.client, "test/model", sleep=api.sleeps.append)), api


BACKENDS = {"system-one": (system_one, system_one_body), "llm": (llm, llm_body)}


@pytest.fixture(params=sorted(BACKENDS))
def backend(
    request: pytest.FixtureRequest,
) -> tuple[Callable[..., tuple[Judge, FakeAPI]], Encoder]:
    return BACKENDS[request.param]


def error(status: int) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"message": f"status {status}", "code": status}})


# --- Contract: every judge ---------------------------------------------------------


def test_answers_every_question_with_its_type(backend: Any) -> None:
    make, encode = backend
    judge, _ = make(encode)

    judgement = judge.ask(STATE, QUESTIONS, purpose="test")

    assert judgement.noul("same_event") == NoulAnswer(SAME_EVENT)
    kind = judgement.choice("kind")
    assert kind.choice == "release"
    assert kind.probabilities == pytest.approx(KIND)
    assert kind.confidence == pytest.approx(0.7)
    fit = judgement.score("fit")
    assert fit.score == pytest.approx(1.6)
    assert fit.probabilities == pytest.approx(FIT)
    assert fit.confidence == pytest.approx(1 - 0.4 / (2 / 3))


def test_answers_keep_the_order_and_names_of_the_questions(backend: Any) -> None:
    make, encode = backend
    judge, _ = make(encode)

    judgement = judge.ask(STATE, QUESTIONS, purpose="test")

    assert list(judgement.answers) == list(QUESTIONS)


def test_asking_for_the_wrong_answer_type_is_an_error(backend: Any) -> None:
    make, encode = backend
    judge, _ = make(encode)

    judgement = judge.ask(STATE, QUESTIONS, purpose="test")

    with pytest.raises(TypeError, match="NoulAnswer"):
        judgement.score("same_event")


def test_usage_is_recorded_with_the_purpose(backend: Any) -> None:
    make, encode = backend
    judge, _ = make(encode)
    meter = UsageMeter()

    judgement = judge.ask(STATE, QUESTIONS, purpose="dedup", meter=meter)

    assert meter.calls == [judgement.usage]
    assert judgement.usage.purpose == "dedup"
    assert judgement.usage.input_tokens == 700


def test_temporary_failures_are_retried(backend: Any) -> None:
    make, encode = backend
    judge, api = make(error(529), error(429), encode)

    judgement = judge.ask(STATE, QUESTIONS, purpose="test")

    assert judgement.noul("same_event").probability == SAME_EVENT
    assert len(api.sleeps) == 2


def test_gives_up_after_the_last_attempt(backend: Any) -> None:
    make, _ = backend
    judge, _ = make(*[error(503)] * ATTEMPTS)

    with pytest.raises(JudgeError, match="gave up"):
        judge.ask(STATE, QUESTIONS, purpose="test")


def test_a_rejected_request_fails_at_once(backend: Any) -> None:
    make, _ = backend
    judge, api = make(error(400))

    with pytest.raises(JudgeError, match="400"):
        judge.ask(STATE, QUESTIONS, purpose="test")
    assert api.sleeps == []


def test_a_missing_answer_is_an_error(backend: Any) -> None:
    make, encode = backend
    judge, api = make(encode)
    api.questions = {"same_event": QUESTIONS["same_event"]}  # the fake forgets the others

    with pytest.raises(JudgeError, match="'kind'"):
        judge.ask(STATE, QUESTIONS, purpose="test")


def test_no_questions_is_a_programming_error(backend: Any) -> None:
    make, _ = backend
    judge, api = make()

    with pytest.raises(ValueError, match="at least one"):
        judge.ask(STATE, {}, purpose="test")
    assert api.requests == []


# --- Questions -------------------------------------------------------------------


def test_a_choice_needs_two_options() -> None:
    with pytest.raises(ValueError, match="2 options"):
        Choice("Which?", {"only": "the one"})


def test_a_score_needs_two_levels() -> None:
    with pytest.raises(ValueError, match="2 levels"):
        Score("How much?", ["only"])


# --- Confidence --------------------------------------------------------------------


def test_confidence_matches_what_system_one_reports() -> None:
    # Answers d1 returned on 2026-10-20 (probabilities and confidence as sent).
    assert choice_confidence([0.9648551543571472, 0.035144845642852716]) == pytest.approx(
        0.9297103087142944
    )
    assert score_confidence(
        [0.0016806864173448943, 0.32028210082191616, 0.6780372127607389]
    ) == pytest.approx(0.5145347895150911)
    assert score_confidence(
        [0.00014393462132807855, 0.001866571680074809, 0.03108121634032156, 0.9669082773582756]
    ) == pytest.approx(0.9647538364355446)


@pytest.mark.parametrize(
    ("probabilities", "expected"),
    [([1, 0, 0], 1.0), ([1 / 3, 1 / 3, 1 / 3], 0.0), ([0.5, 0.5], 0.0)],
)
def test_choice_confidence_bounds(probabilities: list[float], expected: float) -> None:
    assert choice_confidence(probabilities) == pytest.approx(expected)


def test_score_confidence_drops_more_for_probability_further_away() -> None:
    near = score_confidence([0.0, 0.0, 0.2, 0.8])
    far = score_confidence([0.2, 0.0, 0.0, 0.8])

    assert near > far
    assert score_confidence([0.5, 0, 0, 0.5]) == 0.0  # clamped


# --- System One --------------------------------------------------------------------


def test_system_one_request_follows_the_api_shape() -> None:
    judge, api = system_one(system_one_body)

    judge.ask(STATE, QUESTIONS, purpose="test")

    assert str(api.requests[0].url) == "https://judge.test/v1/systemone"
    assert api.body() == {
        "model": "test/model",
        "state": STATE,
        "questions": {
            "same_event": {
                "type": "noul",
                "instructions": "Do `article_a` and `article_b` describe the same event?",
                "criteria": {
                    "true": "Both report the same release.",
                    "false": "Different events, even on one topic.",
                },
            },
            "kind": {
                "type": "choice",
                "instructions": "What kind of article is `article_a`?",
                "criteria": {
                    "release": "A new version",
                    "analysis": "How something works",
                    "news": "Anything else",
                },
            },
            "fit": {
                "type": "score",
                "instructions": {
                    "task": "How well does `article_b` match `interest`?",
                    "priority": "notes first",
                },
                "criteria": ["Unrelated", "Related, not wanted", "Exactly what is wanted"],
            },
        },
    }


def test_system_one_noul_without_criteria_sends_none() -> None:
    judge, api = system_one(system_one_body)
    api.questions = {"promo": Noul("Is it promotion?")}

    judge.ask("text", api.questions, purpose="test")

    assert api.body()["questions"] == {
        "promo": {"type": "noul", "instructions": "Is it promotion?"}
    }


def test_system_one_records_the_served_model_and_cost() -> None:
    judge, _ = system_one(system_one_body)

    usage = judge.ask(STATE, QUESTIONS, purpose="test").usage

    assert usage.model == "test/model-20260917"
    assert usage.cost_usd == 0.00003
    assert usage.output_tokens == 70


def test_system_one_without_cost_reports_none() -> None:
    def body(questions: Mapping[str, Question], model: str) -> dict[str, Any]:
        return {**system_one_body(questions, model), "usage": {"input_tokens": 5}}

    judge, _ = system_one(body)

    usage = judge.ask(STATE, QUESTIONS, purpose="test").usage

    assert usage.cost_usd is None
    assert usage.output_tokens == 0


def test_system_one_error_in_a_200_is_retried() -> None:
    judge, api = system_one(
        httpx2.Response(200, json={"error": {"message": "upstream failed"}}), system_one_body
    )

    judge.ask(STATE, QUESTIONS, purpose="test")

    assert len(api.sleeps) == 1


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        ("same_event", {"type": "choice"}, "expected a noul"),
        ("same_event", {"noul": 1.2}, "not a probability"),
        ("same_event", {"noul": "high"}, "expected a number"),
        ("kind", {"choice": "opinion"}, "unknown option"),
        ("kind", {"probabilities": {"release": 1.0}}, "do not match the options"),
        ("fit", {"probabilities": {"0": 0.5, "1": 0.5}}, "do not match the levels"),
        ("fit", {"score": 3.5}, "outside the levels"),
        ("fit", {"confidence": None}, "expected a number"),
    ],
)
def test_system_one_rejects_answers_that_do_not_fit_the_question(
    name: str, change: dict[str, Any], message: str
) -> None:
    def body(questions: Mapping[str, Question], model: str) -> dict[str, Any]:
        data = system_one_body(questions, model)
        data["answers"][name].update(change)
        return data

    judge, _ = system_one(body)

    with pytest.raises(JudgeError, match=message):
        judge.ask(STATE, QUESTIONS, purpose="test")


# --- Chat model --------------------------------------------------------------------


def test_llm_prompt_carries_state_questions_and_options() -> None:
    judge, api = llm(llm_body)

    judge.ask(STATE, QUESTIONS, purpose="test")

    prompt = api.body()["messages"][-1]["content"]
    assert json.dumps(STATE["interest"], ensure_ascii=False) in prompt
    assert '"same_event" (noul)' in prompt
    assert "Both report the same release." in prompt
    assert "(release, analysis, news)" in prompt
    assert "(0, 1, 2)" in prompt
    assert '"priority": "notes first"' in prompt
    assert api.body()["response_format"] == {"type": "json_object"}


def test_llm_probabilities_are_scaled_and_missing_options_get_zero() -> None:
    answers = {
        "same_event": {"probability": 1.3},
        "kind": {"probabilities": {"release": 2, "news": 2, "opinion": 5}},
        "fit": {"probabilities": {"2": 3, "0": 1}},
    }
    judge, _ = llm(lambda questions, model: chat({"answers": answers}, model))

    judgement = judge.ask(STATE, QUESTIONS, purpose="test")

    assert judgement.noul("same_event").probability == 1.0
    assert judgement.choice("kind") == ChoiceAnswer(
        "release", {"release": 0.5, "analysis": 0.0, "news": 0.5}, 0.25
    )
    fit = judgement.score("fit")
    assert (fit.score, fit.probabilities) == (1.5, (0.25, 0.0, 0.75))
    assert fit.confidence == pytest.approx(1 - 0.5 / (2 / 3))


@pytest.mark.parametrize(
    "answer",
    [{"probabilities": {"release": 0}}, {"probabilities": [0.5, 0.5]}, {"choice": "release"}],
)
def test_llm_unusable_probabilities_are_an_error(answer: dict[str, Any]) -> None:
    answers = {"same_event": {"probability": 0.5}, "kind": answer, "fit": {"probabilities": {}}}
    judge, _ = llm(lambda questions, model: chat({"answers": answers}, model))

    with pytest.raises(JudgeError, match="'kind'"):
        judge.ask(STATE, QUESTIONS, purpose="test")


def test_llm_answer_that_is_not_json_is_an_error() -> None:
    judge, _ = llm(
        lambda questions, model: {
            **chat("", model),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "I think yes."}}],
        }
    )

    with pytest.raises(JudgeError, match="did not return JSON"):
        judge.ask(STATE, QUESTIONS, purpose="test")


# --- Settings ----------------------------------------------------------------------


def test_build_judge_defaults_to_jev_through_the_llm_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "llm-key")

    judge = build_judge(Settings())

    assert isinstance(judge, SystemOneJudge)
    assert judge.model == DEFAULT_SYSTEM_ONE_MODEL
    assert str(judge.client.base_url) == "https://openrouter.ai/api/v1/"
    assert judge.client.api_key == "llm-key"


def test_build_judge_llm_backend_uses_the_llm_settings_with_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JUDGE_BACKEND", "llm")
    monkeypatch.setenv("LLM_MODEL", "chat/model")
    monkeypatch.setenv("JUDGE_BASE_URL", "http://ollama:11434/v1")

    judge = build_judge(Settings())

    assert isinstance(judge, LLMJudge)
    assert judge.model == "chat/model"
    assert str(judge.llm.client.base_url) == "http://ollama:11434/v1/"


def test_llm_score_keyed_by_level_text_is_understood() -> None:
    answers = {
        "same_event": {"probability": 0.5},
        "kind": {"probabilities": {"release": 1}},
        "fit": {"probabilities": {"Unrelated": 0.0, " related, not wanted ": 1, "2": 3}},
    }
    judge, api = llm(lambda questions, model: chat({"answers": answers}, model))

    fit = judge.ask(STATE, QUESTIONS, purpose="test").score("fit")

    assert fit.probabilities == (0.0, 0.25, 0.75)
    prompt = api.body()["messages"][-1]["content"]
    assert "  0: Unrelated\n  1: Related, not wanted\n" in prompt
