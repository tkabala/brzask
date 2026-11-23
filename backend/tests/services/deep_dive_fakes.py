"""Fakes shared by the deep dive tests."""

from brzask.clients.usage import UsageMeter
from brzask.clients.web_search import SearchResult


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
