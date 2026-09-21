import json
import os
from pathlib import Path

import yaml

from docker_agent.config import get_settings
from docker_agent.deployment import production_preflight

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
        assert production_preflight(env_file=None) == 0
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


def test_production_preflight_does_not_mutate_app_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
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
    monkeypatch.setenv("TOOL_MODE", "mock")

    assert production_preflight(env_file=None) == 0
    assert os.environ["APP_ENV"] == "development"


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
        assert production_preflight(env_file=None) == 2
        captured = capsys.readouterr()

        assert "do-not-print-this-value" not in captured.err
        assert "APP_LOG_LEVEL is not supported" in captured.err
    finally:
        get_settings.cache_clear()


def test_prometheus_example_scrapes_internal_backend_metrics() -> None:
    config = yaml.safe_load(
        (ROOT / "docker/prometheus/prometheus.yml").read_text(
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


def test_production_smoke_checks_spa_readiness_and_private_metrics() -> None:
    smoke = (ROOT / "web/scripts/production-smoke.mjs").read_text(
        encoding="utf-8"
    )

    assert '["/", "/operations", "/settings"]' in smoke
    assert "/health/ready" in smoke
    assert "/metrics" in smoke
    assert "status === 404" in smoke


def test_deployment_runbook_covers_backup_rollback_and_restore() -> None:
    runbook = (ROOT / "doc/Production_Runbook.md").read_text(
        encoding="utf-8"
    )

    assert "production_preflight.py" in runbook
    assert "pg_dump" in runbook
    assert "alembic downgrade -1" in runbook
    assert "## 9. Database Restore" in runbook
    assert "Final Production Smoke" in runbook
    assert "Evaluation Regression Gate" in runbook
    assert "down -v" in runbook


def test_production_preflight_never_prints_full_database_url() -> None:
    script = (ROOT / "src/docker_agent/deployment.py").read_text(
        encoding="utf-8"
    )

    assert '"host": database.host' in script
    assert '"database": database.database' in script
    assert '"api_key_configured": bool(settings.model_api_key)' in script
    assert '"database_url": settings.database_url' not in script
    assert '"api_key": settings.model_api_key' not in script
