from fastapi.testclient import TestClient

from docker_agent.main import app
from docker_agent.observability import metrics


def test_http_middleware_preserves_safe_request_id_and_records_metric() -> None:
    metrics.reset()
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"X-Request-ID": "request-test-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-test-123"

    metric_response = client.get("/metrics")
    assert metric_response.status_code == 200
    assert metric_response.headers["content-type"].startswith(
        "text/plain; version=0.0.4"
    )
    assert (
        'docker_agent_http_requests_total{method="GET",'
        'route="/health",status="200"} 1'
    ) in metric_response.text


def test_http_middleware_replaces_invalid_request_id() -> None:
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"X-Request-ID": "not safe with spaces"},
    )

    request_id = response.headers["X-Request-ID"]
    assert request_id != "not safe with spaces"
    assert len(request_id) == 32
    assert request_id.isalnum()


def test_metrics_endpoint_does_not_count_its_own_scrapes() -> None:
    metrics.reset()
    client = TestClient(app)

    first = client.get("/metrics")
    second = client.get("/metrics")

    assert first.status_code == 200
    assert second.status_code == 200
    assert 'route="/metrics"' not in second.text
