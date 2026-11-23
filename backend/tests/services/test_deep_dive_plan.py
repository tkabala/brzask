from typing import Any

import pytest

from brzask import prompts
from brzask.clients.llm import LLMError
from brzask.db.models import Article, ArticleContent, ContentKind
from brzask.services.deep_dive.plan import Queries, parse_queries, plan_queries
from tests.services.test_briefs import FakeLLM

TITLE = "Proxmox 9 released"


def test_a_full_answer() -> None:
    answer = {"background": ["a", "b"], "practice": ["c"], "archive": ["d"]}
    assert parse_queries(answer, TITLE) == Queries(["a", "b"], ["c"], ["d"])


def test_lists_are_cut_to_their_maxima() -> None:
    answer = {
        "background": [f"b{n}" for n in range(6)],
        "practice": [f"p{n}" for n in range(6)],
        "archive": [f"a{n}" for n in range(6)],
    }
    queries = parse_queries(answer, TITLE)
    assert (len(queries.background), len(queries.practice), len(queries.archive)) == (3, 3, 2)


def test_blank_queries_and_repeats_are_dropped() -> None:
    answer = {"background": ["  ", "Proxmox  ", "proxmox", 7, "zfs"], "practice": []}
    assert parse_queries(answer, TITLE) == Queries(["Proxmox", "zfs"], [], [])


def test_a_long_query_is_cut() -> None:
    queries = parse_queries({"background": ["x" * 500]}, TITLE)
    assert queries.background == ["x" * 200]


@pytest.mark.parametrize("answer", [{}, "text", None, {"background": [], "practice": ["  "]}])
def test_an_unusable_answer_falls_back_to_the_title(answer: Any) -> None:
    assert parse_queries(answer, TITLE) == Queries([TITLE], [], [TITLE])


def article() -> tuple[Article, ArticleContent]:
    item = Article(id=1, title=TITLE, link="https://pve.example/9")
    content = ArticleContent(article_id=1, text="Proxmox 9 is out.", kind=ContentKind.PAGE)
    return item, content


def test_plan_asks_the_model() -> None:
    llm = FakeLLM(lambda _prompt, _n: {"background": ["q"], "practice": [], "archive": []})
    item, content = article()

    queries = plan_queries(llm, item, None, content, [], "on ZFS", prompts.language("en"), None)

    assert queries == Queries(["q"], [], [])
    assert llm.purposes == ["deep_dive_plan"]
    assert "on ZFS" in llm.prompts[0]


@pytest.mark.parametrize("failure", [LLMError("down"), "not json"])
def test_plan_falls_back_to_the_title_when_the_model_fails(failure: Any) -> None:
    llm = FakeLLM(lambda _prompt, _n: failure)
    item, content = article()

    queries = plan_queries(llm, item, None, content, [], "", prompts.language("en"), None)

    assert queries == Queries([TITLE], [], [TITLE])
