"""The agent skills in `skills/` and the Claude Code plugin that ships them."""

import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from sqlalchemy.orm import Session, sessionmaker

from brzask.api.clients import ApiClients
from brzask.mcp.runs import BackgroundRuns
from brzask.mcp.server import McpDeps, build_mcp

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
# A tool call as the skills write it: `name(` inside backticks.
TOOL_CALL = re.compile(r"`([a-z_]+)\(")


def frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text()
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match, f"{path} has no frontmatter"
    meta = yaml.safe_load(match.group(1))
    assert isinstance(meta, dict)
    return meta, match.group(2)


@pytest.fixture(scope="module")
def tool_names() -> set[str]:
    deps = McpDeps(
        sessionmaker[Session](),
        ApiClients(feed_finder=lambda: nullcontext(None)),  # type: ignore[arg-type]
        BackgroundRuns(sessionmaker[Session]()),
    )
    server = build_mcp(deps)
    return {tool.name for tool in anyio.run(server.list_tools)}


def test_the_four_skills_exist() -> None:
    assert [path.parent.name for path in SKILLS] == [
        "empty-digest",
        "explain-pick",
        "onboarding",
        "weekly-tune-up",
    ]


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_a_skill_names_itself_and_says_when_to_use_it(path: Path) -> None:
    meta, body = frontmatter(path)

    assert meta["name"] == path.parent.name
    assert 0 < len(meta["description"]) <= 1024
    assert body.strip()


@pytest.mark.parametrize("path", SKILLS, ids=lambda path: path.parent.name)
def test_a_skill_calls_only_tools_the_server_has(path: Path, tool_names: set[str]) -> None:
    _, body = frontmatter(path)

    called = set(TOOL_CALL.findall(body))

    assert called, f"{path} calls no tools"
    assert called <= tool_names, sorted(called - tool_names)


def test_the_plugin_ships_the_skills() -> None:
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())

    (entry,) = marketplace["plugins"]
    assert entry["name"] == plugin["name"] == "brzask"
    assert (ROOT / entry["source"] / "skills").is_dir()
