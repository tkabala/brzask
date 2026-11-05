from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from tests.factories import Factories


def test_metrics_count_api_requests(client: TestClient) -> None:
    client.get("/api/v1/runs")
    client.get("/healthz")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = [line for line in response.text.splitlines() if line.startswith("http_server_")]
    assert any(
        line.startswith("http_server_request_duration_seconds_count")
        and 'http_route="/api/v1/runs"' in line
        and 'http_response_status_code="200"' in line
        for line in lines
    )
    # Probes and scrapes are not measured.
    assert not any("/healthz" in line or "/metrics" in line for line in lines)


def test_metrics_show_the_open_rate(client: TestClient, make: Factories) -> None:
    make.article(digest_date=date(2026, 11, 5), opened_at=datetime(2026, 11, 5, 9, tzinfo=UTC))
    make.article(digest_date=date(2026, 11, 5))
    make.session.flush()

    lines = client.get("/metrics").text.splitlines()

    def value(name: str) -> str:
        [line] = [line for line in lines if line.startswith(name + "{")]
        assert 'days="7"' in line
        return line.rsplit(" ", 1)[1]

    assert value("brzask_digest_shown") == "2.0"
    assert value("brzask_digest_opened") == "1.0"
