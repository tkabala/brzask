from datetime import date

from sqlalchemy.orm import Session

from brzask.clients.extractors.base import ExtractionInput
from brzask.clients.extractors.chain import SNIPPET, ExtractionResult
from brzask.clients.usage import UsageMeter
from brzask.clients.web_search import SearchResult, WebSearchError
from brzask.db.models import Article, ArticleContent, ContentKind
from brzask.services.deep_dive.gather import (
    SOURCE_CHARS,
    archive_candidates,
    clip_source,
    read_sources,
    round_robin,
    web_candidates,
)
from brzask.services.deep_dive.plan import Queries
from tests.factories import Factories
from tests.services.digest.fakes import FakeEmbedder, FakeExtractor

LINK = "https://pve.example/news/9"


def result(name: str, url: str | None = None) -> SearchResult:
    return SearchResult(url or f"https://{name}.example/", name, f"about {name}")


def test_round_robin() -> None:
    a1, a2, b1, c1, c2, c3 = (result(n) for n in ("a1", "a2", "b1", "c1", "c2", "c3"))
    assert round_robin([[a1, a2], [b1], [c1, c2, c3]]) == [a1, b1, c1, a2, c2, c3]
    assert round_robin([]) == []


class FakeSearch:
    name = "fake"

    def __init__(self, answers: dict[str, list[SearchResult] | Exception]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    def search(
        self, query: str, *, limit: int = 10, meter: UsageMeter | None = None
    ) -> list[SearchResult]:
        self.calls.append((query, limit))
        answer = self.answers[query]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:
        pass


def test_web_candidates_drop_the_article_and_repeats() -> None:
    search = FakeSearch(
        {
            "b": [result("same", LINK + "/"), result("x"), result("y")],
            "p": [result("x"), result("z")],
        }
    )

    found, answered = web_candidates(Queries(["b"], ["p"], ["archive only"]), search, LINK, None)

    assert [r.title for r in found] == ["x", "z", "y"]  # round robin: x, (x), z, y
    assert answered
    assert search.calls == [("b", 5), ("p", 5)]


def test_non_http_results_are_dropped() -> None:
    search = FakeSearch(
        {
            "b": [
                result("js", "javascript:alert(1)"),
                result("ftp", "ftp://files.example/x"),
                result("empty", " "),
                result("ok"),
            ]
        }
    )
    found, _ = web_candidates(Queries(["b"], [], []), search, LINK, None)
    assert [r.title for r in found] == ["ok"]


def test_a_failing_search_is_skipped() -> None:
    search = FakeSearch({"a": [result("a")], "b": WebSearchError("down"), "c": [result("c")]})
    found, answered = web_candidates(Queries(["a", "b"], ["c"], []), search, LINK, None)
    assert ([r.title for r in found], answered) == (["a", "c"], True)


def test_all_searches_failing_reports_no_web() -> None:
    search = FakeSearch({"a": WebSearchError("down"), "b": WebSearchError("down")})
    assert web_candidates(Queries(["a"], ["b"], []), search, LINK, None) == ([], False)


def test_archive_candidates(session: Session, make: Factories) -> None:
    embedder = FakeEmbedder()
    [query_vector] = embedder.embed(["proxmox"], "query")
    itself = make.article(title="Proxmox itself", embedding=query_vector)
    near = make.article(title="Unrelated title", embedding=query_vector)
    texts = [make.article(title=f"Proxmox note {n}") for n in range(6)]

    found = archive_candidates(session, embedder, ["proxmox"], itself.id)

    assert itself not in found
    assert found[0] == near  # the vector match first, then text matches newest first
    assert found[1:] == list(reversed(texts))[:4]


def test_archive_candidates_order_shown_first(session: Session, make: Factories) -> None:
    itself = make.article(title="Subject")
    unseen = make.article(title="zfs tuning")
    shown = make.article(title="zfs tuning, shown", digest_date=date(2026, 11, 1))

    found = archive_candidates(session, FakeEmbedder(), ["zfs tuning"], itself.id)

    assert found == [shown, unseen]


def test_clip_source() -> None:
    text = ("word " * 100 + "\n\n") * 100  # ~50,000 characters
    clipped = clip_source(text)
    assert len(clipped) <= SOURCE_CHARS
    assert text.startswith(clipped)
    assert clipped.endswith("word")
    assert clip_source("short") == "short"


def subject() -> tuple[Article, ArticleContent]:
    article = Article(id=1, title="Proxmox 9", digest_title="Proxmox 9 is out", link=LINK)
    content = ArticleContent(article_id=1, text="The article.", kind=ContentKind.PAGE)
    return article, content


def test_read_sources_numbers_in_order() -> None:
    article, content = subject()
    with_content = Article(id=2, title="Older", link="https://a.example/2")
    with_extract = Article(id=3, title="Other", link="https://a.example/3", extracted_text="ex")
    without_text = Article(id=4, title="Empty", link="https://a.example/4")
    web = [result("good"), result("snippet-only"), result("long")]
    extractor = FakeExtractor(
        {"https://good.example/": "good page", "https://long.example/": "para\n\n" * 6000}
    )

    sources = read_sources(
        article,
        content,
        [with_content, with_extract, without_text],
        {2: "stored text"},
        web,
        extractor,
    )

    assert [(s.n, s.origin, s.title) for s in sources] == [
        (1, "article", "Proxmox 9 is out"),
        (2, "archive", "Older"),
        (3, "archive", "Other"),
        (4, "web", "good"),
        (5, "web", "long"),
    ]
    assert [s.text for s in sources[:4]] == ["The article.", "stored text", "ex", "good page"]
    assert len(sources[4].text) <= SOURCE_CHARS
    assert [s.article_id for s in sources] == [1, 2, 3, None, None]
    assert {i.url for i in extractor.inputs} == {r.url for r in web}


def test_only_the_first_pages_are_read() -> None:
    article, content = subject()
    web = [result(f"r{n}") for n in range(12)]
    extractor = FakeExtractor({r.url: "text" for r in web})

    sources = read_sources(article, content, [], {}, web, extractor)

    assert [s.title for s in sources[1:]] == [f"r{n}" for n in range(8)]
    assert len(extractor.inputs) == 8


def test_nothing_but_the_article() -> None:
    article, content = subject()
    sources = read_sources(article, content, [], {}, [], FakeExtractor())
    assert [(s.n, s.url) for s in sources] == [(1, LINK)]


def test_a_failed_extraction_is_dropped() -> None:
    class Failing:
        def extract(self, item: ExtractionInput) -> ExtractionResult:
            if "bad" in item.url:
                raise RuntimeError("boom")
            return ExtractionResult(item.snippet, SNIPPET)

    article, content = subject()
    sources = read_sources(article, content, [], {}, [result("bad"), result("ok")], Failing())
    assert len(sources) == 1
