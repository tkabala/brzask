from fastapi.testclient import TestClient


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
