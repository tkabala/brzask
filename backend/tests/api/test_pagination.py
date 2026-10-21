import pytest

from brzask.api.pagination import decode_cursor, encode_cursor, page
from brzask.api.problems import ProblemError


def test_cursor_round_trip() -> None:
    cursor = encode_cursor(["2026-10-21T07:00:00+00:00", "abc"])

    assert "=" not in cursor
    assert decode_cursor(cursor, tuple) == ("2026-10-21T07:00:00+00:00", "abc")


def test_no_cursor_means_the_first_page() -> None:
    assert decode_cursor(None, tuple) is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        "AAAA",  # bytes that are not UTF-8
        "e30",  # {}: not a list
        "WzFd",  # [1]: not strings
    ],
)
def test_malformed_cursor_is_a_bad_request(cursor: str) -> None:
    with pytest.raises(ProblemError) as raised:
        decode_cursor(cursor, tuple)
    assert raised.value.status == 400


def test_cursor_the_parser_rejects_is_a_bad_request() -> None:
    def parse(values: list[str]) -> int:
        return int(values[0])

    with pytest.raises(ProblemError):
        decode_cursor(encode_cursor(["x"]), parse)


def test_page_has_a_cursor_only_when_more_rows_follow() -> None:
    def key(n: int) -> list[str]:
        return [str(n)]

    assert page([1, 2, 3], 2, key) == ([1, 2], encode_cursor(["2"]))
    assert page([1, 2], 2, key) == ([1, 2], None)
    assert page([], 2, key) == ([], None)
