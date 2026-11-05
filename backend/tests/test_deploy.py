"""The compose file: what runs by default and what the observability profile adds."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from brzask.clients.extractors.chain import ATTEMPTS_METRIC
from brzask.services.open_rate import OPENED, SHOWN
from brzask.services.run_metrics import INSTRUMENTS

DEPLOY = Path(__file__).parents[2] / "deploy"
OBSERVABILITY = ("otel-collector", "prometheus", "tempo", "grafana")
DEFAULT = ("db", "migrate", "api", "worker")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((DEPLOY / "compose.yaml").read_text())
    return loaded


def test_the_default_deployment_stays_four_services(compose: dict[str, Any]) -> None:
    services = compose["services"]
    default = [name for name, service in services.items() if "profiles" not in service]
    assert sorted(default) == sorted(DEFAULT)


def test_observability_services_are_opt_in(compose: dict[str, Any]) -> None:
    for name in OBSERVABILITY:
        assert compose["services"][name]["profiles"] == ["observability"], name


def test_images_are_pinned(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        image = service.get("image", "")
        if image.startswith("${BRZASK_IMAGE"):
            continue
        assert re.fullmatch(r"[\w./-]+:v?\d+\.\d+\.\d+[\w.-]*", image), (name, image)


def test_grafana_is_loopback_by_default(compose: dict[str, Any]) -> None:
    services = compose["services"]
    assert services["grafana"]["ports"] == ["${GRAFANA_PUBLISH:-127.0.0.1:3000}:3000"]
    for name in ("otel-collector", "prometheus", "tempo"):
        assert "ports" not in services[name], name


def test_the_otlp_endpoint_is_not_defaulted(compose: dict[str, Any]) -> None:
    # A default would make every deployment without the profile log export errors.
    environments = [compose["x-brzask"]["environment"]] + [
        service.get("environment", {}) for service in compose["services"].values()
    ]
    assert not any("OTEL_EXPORTER_OTLP_ENDPOINT" in environment for environment in environments)


def test_mounted_files_exist(compose: dict[str, Any]) -> None:
    for name in OBSERVABILITY:
        for volume in compose["services"][name].get("volumes", []):
            source = volume.split(":", 1)[0]
            if source.startswith("./observability/"):
                assert (DEPLOY / source).exists(), (name, source)


def test_secrets_are_declared(compose: dict[str, Any]) -> None:
    declared = set(compose["secrets"])
    for name, service in compose["services"].items():
        for secret in service.get("secrets", []):
            assert (secret if isinstance(secret, str) else secret["source"]) in declared, name


def test_grafana_makes_no_outside_requests(compose: dict[str, Any]) -> None:
    environment = compose["services"]["grafana"]["environment"]
    for setting in (
        "GF_ANALYTICS_REPORTING_ENABLED",
        "GF_ANALYTICS_CHECK_FOR_UPDATES",
        "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES",
        "GF_NEWS_NEWS_FEED_ENABLED",
    ):
        assert environment[setting] == "false", setting
    assert environment["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert environment["GF_SECURITY_ADMIN_PASSWORD__FILE"] == "/run/secrets/grafana_admin_password"


@pytest.mark.parametrize(
    "path", sorted((DEPLOY / "observability").rglob("*.yaml")), ids=lambda path: path.name
)
def test_observability_config_parses(path: Path) -> None:
    assert isinstance(yaml.safe_load(path.read_text()), dict)


# --- dashboard ------------------------------------------------------------------

DASHBOARD = DEPLOY / "observability" / "grafana" / "dashboards" / "brzask.json"
# What Prometheus' OTLP receiver appends: the unit, then _total or a histogram series.
_SUFFIXES = re.compile(r"(_(seconds|USD))?(_total|_bucket|_sum|_count)?$")


def _targets(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return [target for panel in dashboard["panels"] for target in panel.get("targets", [])]


def test_dashboard_queries_known_metrics() -> None:
    dashboard = json.loads(DASHBOARD.read_text())
    known = {name.replace(".", "_") for name in (*INSTRUMENTS, SHOWN, OPENED, ATTEMPTS_METRIC)}
    used = {
        _SUFFIXES.sub("", name)
        for target in _targets(dashboard)
        for name in re.findall(r"\bbrzask_[a-z_A-Z]+", target.get("expr", ""))
    }
    assert used, "the dashboard queries no brzask metric"
    assert used <= known, used - known
    # Every instrument has a panel.
    assert known <= used, known - used


def test_dashboard_uses_the_provisioned_datasources() -> None:
    dashboard = json.loads(DASHBOARD.read_text())
    assert dashboard["uid"] == "brzask"
    for panel in dashboard["panels"]:
        if panel["type"] == "row":
            continue
        assert panel["datasource"]["uid"] in {"prometheus", "tempo"}, panel["title"]
    [dry_run] = dashboard["templating"]["list"]
    assert dry_run["name"] == "dry_run"
    assert dry_run["current"]["value"] == "false"


def test_the_home_dashboard_is_provisioned(compose: dict[str, Any]) -> None:
    environment = compose["services"]["grafana"]["environment"]
    path = environment["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"]
    assert path == "/var/lib/grafana/dashboards/" + DASHBOARD.name


def test_daily_counts_are_exact(compose: dict[str, Any]) -> None:
    # A process's counters start anew and see a point or two a day: increase()
    # needs the zero at the start time and an anchored (not extrapolated) range.
    flags = ",".join(
        flag.split("=", 1)[1]
        for flag in compose["services"]["prometheus"]["command"]
        if flag.startswith("--enable-feature=")
    ).split(",")
    assert {"created-timestamp-zero-ingestion", "promql-extended-range-selectors"} <= set(flags)
    dashboard = json.loads(DASHBOARD.read_text())
    for target in _targets(dashboard):
        for call in re.findall(r"increase\([^\[]*\[[^\]]+\]\s*\w*", target.get("expr", "")):
            assert call.endswith("anchored"), call
