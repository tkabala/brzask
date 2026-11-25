"""docs/privacy.md lists every outside service brzask can talk to."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from brzask.clients.extractors.adapters import JinaExtractor
from brzask.clients.feed_finder import GITHUB_API
from brzask.clients.web_search import BRAVE_URL
from brzask.config.settings import GROUPS, env_name

PRIVACY = Path(__file__).parents[2] / "docs" / "privacy.md"

# Settings that name a place or a credential for one: each is an outside service.
_SERVICE_SETTING = re.compile(r"_(URL|URLS|DSN|ENDPOINT|API_KEY|API_TOKEN)$")
# The address brzask itself is served at, not one it sends to.
_OWN_ADDRESS = {"BASE_URL"}


def _service_settings() -> list[str]:
    names = (env_name(group, field) for group in GROUPS for field in group.model_fields)
    return [name for name in names if _SERVICE_SETTING.search(name) and name not in _OWN_ADDRESS]


def test_there_are_service_settings_to_check() -> None:
    assert "LLM_BASE_URL" in _service_settings()


@pytest.mark.parametrize("name", _service_settings())
def test_every_service_setting_is_listed(name: str) -> None:
    assert f"`{name}`" in PRIVACY.read_text(), f"docs/privacy.md does not mention {name}"


@pytest.mark.parametrize("url", [JinaExtractor.endpoint, GITHUB_API, BRAVE_URL])
def test_every_built_in_service_host_is_listed(url: str) -> None:
    host = urlsplit(url).hostname
    assert host is not None
    assert host in PRIVACY.read_text(), f"docs/privacy.md does not mention {host}"
