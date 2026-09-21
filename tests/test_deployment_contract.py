import json
from pathlib import Path

import yaml

from docker_agent.config import get_settings
from scripts.production_preflight import main as production_preflight

ROOT = Path(__file__).resolve().parents[1]


def test_production_preflight_reports_safe_summary(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        (
            "postgresql+psycopg://docker_agent:"
            "very-secret-db-password@postgres:5432/docker_agent"
        ),
    )
    monkeypatch.setenv("MODEL_NAME", "release-model")
    monkeypatch.setenv(
        "MODEL_BASE_URL",
        "https://model.example/v1",
    )
    monkeypatch.setenv("MODEL_API_KEY", "super-secret-model-key")
    monkeypatch.setenv("TOOL_MODE", "mock")
    get_settings.cache_clear()

    try:
        assert production_preflight() == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert payload["status"] == "ok"
        assert payload["app_env"] == "production"
        assert payload["database"] == {
            "backend": "postgresql",
            "host": "postgres",
            "port": 5432,
            "database": "docker_agent",
        }
        assert payload["model"] == {
            "name": "release-model",
            "api_key_configured": True,
        }
        assert "very-secret-db-password" not in captured.out
        assert "super-secret-model-key" not in captured.out
    finally:
        get_settings.cache_clear()


def test_production_preflight_hides_invalid_input_values(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        (
            "postgresql+psycopg://docker_agent:"
            "strong-password@postgres:5432/docker_agent"
        ),
    )
    monkeypatch.setenv("MODEL_NAME", "release-model")
    monkeypatch.setenv(
        "MODEL_BASE_URL",
        "https://model.example/v1",
    )
    monkeypatch.setenv("APP_LOG_LEVEL", "do-not-print-this-value")
    get_settings.cache_clear()

    try:
        assert production_preflight() == 2
        captured = capsys.readouterr()

        assert "do-not-print-this-value" not in captured.err
        assert "APP_LOG_LEVEL is not supported" in captured.err
    finally:
        get_settings.cache_clear()


def test_prometheus_example_scrapes_internal_backend_metrics() -> None:
    config = yaml.safe_load(
        (ROOT / "deploy/prometheus.yml").read_text(
            encoding="utf-8"
        )
    )

    assert config["global"]["scrape_interval"] == "15s"
    scrape = config["scrape_configs"][0]
    assert scrape["job_name"] == "docker-support-agent"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["static_configs"][0]["targets"] == [
        "backend:8000"
    ]


def test_production_smoke_checks_spa_readiness_and_metrics() -> None:
    smoke = (ROOT / "web/scripts/production-smoke.mjs").read_text(
        encoding="utf-8"
    )

    assert '["/", "/operations", "/settings"]' in smoke
    assert "/health/ready" in smoke
    assert "/metrics" in smoke
    assert "docker_agent_run_duration_seconds" in smoke
