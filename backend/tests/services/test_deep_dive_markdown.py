from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from brzask import prompts
from brzask.db.models import Article, DeepDive, DeepDiveStatus
from brzask.services.deep_dive.markdown import escape, filename, render

FINISHED = datetime(2026, 11, 23, 9, 30, tzinfo=UTC)
ARTICLE = Article(
    id=1, title="Proxmox 9 released", digest_title="Proxmox 9 is out", link="https://pve.example/9"
)


def dive(**fields: object) -> DeepDive:
    values: dict[str, object] = {
        "id": 7,
        "article_id": 1,
        "focus": "",
        "status": DeepDiveStatus.DONE,
        "finished_at": FINISHED,
        "report": {
            "background": [{"text": "Proxmox moved to Debian 13.", "sources": [1, 2]}],
            "practice": [
                {"text": "Upgrade a node.", "command": "pve8to9 --full", "sources": [2]},
                {"text": "Read the notes first.", "command": None, "sources": []},
            ],
            "further": [{"source": 2, "why": "The official upgrade guide."}],
        },
        "sources": [
            {
                "n": 1,
                "url": "https://pve.example/9",
                "title": "Proxmox 9 is out",
                "origin": "article",
            },
            {
                "n": 2,
                "url": "https://wiki.example/Upgrade",
                "title": "Upgrade 8 to 9",
                "origin": "web",
            },
        ],
    }
    values.update(fields)
    return DeepDive(**values)


ENGLISH = """# Proxmox 9 is out

2026-11-23 · https://pve.example/9

## Background

Proxmox moved to Debian 13. [1][2]

## In practice

1. Upgrade a node. [2]

   ```
   pve8to9 --full
   ```

2. Read the notes first.

## Further reading

- [Upgrade 8 to 9](https://wiki.example/Upgrade): The official upgrade guide.

## Sources

1. [Proxmox 9 is out](https://pve.example/9)
2. [Upgrade 8 to 9](https://wiki.example/Upgrade)
"""


def test_english() -> None:
    assert render(dive(), ARTICLE, prompts.language("en")) == ENGLISH


def test_polish_headings_and_focus() -> None:
    text = render(dive(focus="dla klastra"), ARTICLE, prompts.language("pl"))

    assert "\nUkierunkowanie: dla klastra\n" in text
    for heading in ("## Tło", "## W praktyce", "## Co dalej czytać", "## Źródła"):
        assert f"\n{heading}\n" in text


def test_focus_line_only_when_set() -> None:
    assert "Focus:" not in render(dive(), ARTICLE, prompts.language("en"))
    assert "\nFocus: on ZFS\n" in render(dive(focus="on ZFS"), ARTICLE, prompts.language("en"))


def test_no_practice_says_so() -> None:
    report = {**dive().report, "practice": []}  # type: ignore[dict-item]
    text = render(dive(report=report), ARTICLE, prompts.language("en"))
    assert "## In practice\n\nNothing practical to try here.\n" in text


def test_hostile_title_cannot_change_a_link() -> None:
    sources = [
        {"n": 1, "url": "https://pve.example/9", "title": "T", "origin": "article"},
        {
            "n": 2,
            "url": "https://wiki.example/x",
            "title": "x](javascript:alert(1)) [y",
            "origin": "web",
        },
    ]
    text = render(dive(sources=sources), ARTICLE, prompts.language("en"))

    for line in text.splitlines():
        if "javascript" in line:
            assert line.count("](") - line.count("\\](") == 1
            assert "](https://wiki.example/x)" in line


def test_url_cannot_close_its_link() -> None:
    sources = [
        {"n": 1, "url": "https://pve.example/9", "title": "T", "origin": "article"},
        {"n": 2, "url": "https://w.example/a b)(c<d>", "title": "W", "origin": "web"},
    ]
    text = render(dive(sources=sources), ARTICLE, prompts.language("en"))
    assert "[W](https://w.example/a%20b%29%28c%3Cd%3E)" in text


def test_command_with_a_code_fence_uses_a_longer_fence() -> None:
    report = {
        "background": [{"text": "b", "sources": []}],
        "practice": [{"text": "s", "command": "echo ```\nls", "sources": []}],
        "further": [],
    }
    text = render(dive(report=report), ARTICLE, prompts.language("en"))
    assert "   ````\n   echo ```\n   ls\n   ````\n" in text


def test_title_with_newlines_and_hashes_stays_one_line() -> None:
    article = Article(
        id=1, title="t", digest_title="# Big\n\n## news", link="https://pve.example/9"
    )
    text = render(dive(), article, prompts.language("en"))
    assert text.startswith("# \\# Big \\#\\# news\n")


def test_escape() -> None:
    assert escape("a [b] (c) *e* _f_ #g <h> \\i\nj") == (
        "a \\[b\\] (c) \\*e\\* \\_f\\_ \\#g \\<h\\> \\\\i j"
    )


def test_inline_code_stays_code() -> None:
    assert escape("use `--start-dir` [x]") == "use `--start-dir` \\[x\\]"
    assert escape("a lone ` tick") == "a lone \\` tick"


def test_tracking_parameters_leave_the_article_link() -> None:
    article = Article(
        id=1,
        title="t",
        digest_title="T",
        link="https://a.example/p?id=3&utm_source=rss&utm_medium=x",
    )
    assert "\n2026-11-23 · https://a.example/p?id=3\n" in render(
        dive(), article, prompts.language("en")
    )


def test_filename() -> None:
    article = Article(id=1, title="t", digest_title="Łódź: ceny mieszkań rosną", link="x")
    assert filename(dive(), article) == "2026-11-23-lodz-ceny-mieszkan-rosna.md"

    long = Article(id=1, title="t", digest_title="word " * 40, link="x")
    name = filename(dive(), long)
    slug = name.removeprefix("2026-11-23-").removesuffix(".md")
    assert len(slug) <= 60
    assert not slug.endswith("-")

    empty = Article(id=1, title="!!!", digest_title=None, link="x")
    assert filename(dive(), empty) == "2026-11-23-deep-dive.md"


def test_bare_urls_stay_text() -> None:
    # GFM notes apps link bare URLs and www. names; a report links only its sources.
    assert escape("see https://evil.example/x or www.evil.example") == (
        "see https\\://evil.example/x or www\\.evil.example"
    )
    assert escape("HTTP://a.example and ftp://b.example") == (
        "HTTP\\://a.example and ftp\\://b.example"
    )
    assert escape("`curl https://get.example`") == "`curl https://get.example`"
    assert escape("Proxmox 9.1 released") == "Proxmox 9.1 released"


def test_text_cannot_start_a_block() -> None:
    assert escape("1. first") == "1\\. first"
    assert escape("12) twelfth") == "12\\) twelfth"
    assert escape("- item") == "\\- item"
    assert escape("+ item") == "\\+ item"
    assert escape("===") == "\\==="
    assert escape("2026 was a year. a - b") == "2026 was a year. a - b"


def test_dates_in_the_given_timezone() -> None:
    late = dive(finished_at=datetime(2026, 11, 23, 23, 30, tzinfo=UTC))
    warsaw = ZoneInfo("Europe/Warsaw")
    assert filename(late, ARTICLE, warsaw).startswith("2026-11-24-")
    assert "\n2026-11-24 · " in render(late, ARTICLE, prompts.language("en"), warsaw)
    assert filename(late, ARTICLE).startswith("2026-11-23-")
