from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_runbook_covers_required_operational_procedures() -> None:
    runbook = _read("doc/Production_Runbook.md")

    required_sections = (
        "## 2. Preflight",
        "## 5. Health and Readiness",
        "## 6. Final Production Smoke",
        "## 7. Prometheus Monitoring",
        "## 8. Database Backup",
        "## 9. Database Restore",
        "## 10. Upgrade Procedure",
        "## 11. Rollback Procedure",
        "## 12. Knowledge-Base Operations",
        "## 13. Incident Checklist",
        "## 14. Shutdown and Data Retention",
    )
    for section in required_sections:
        assert section in runbook

    assert "pg_dump" in runbook
    assert "pg_restore" in runbook
    assert "alembic upgrade head" in runbook
    assert "alembic downgrade -1" in runbook
    assert "SMOKE_CHECK_METRICS" in runbook
    assert "--profile monitoring" in runbook


def test_monitoring_profile_is_optional_and_uses_persistent_storage() -> None:
    compose = yaml.safe_load(_read("compose.prod.yaml"))
    prometheus = compose["services"]["prometheus"]

    assert prometheus["profiles"] == ["monitoring"]
    assert prometheus["depends_on"]["backend"] == {
        "condition": "service_healthy"
    }
    assert "./docker/prometheus/prometheus.yml:" in " ".join(
        prometheus["volumes"]
    )
    assert "prometheus_data:/prometheus" in prometheus["volumes"]
    assert "prometheus_data" in compose["volumes"]


def test_prometheus_scrape_contract_targets_private_backend_metrics() -> None:
    config = yaml.safe_load(
        _read("docker/prometheus/prometheus.yml")
    )
    scrape = config["scrape_configs"][0]

    assert scrape["job_name"] == "docker-support-agent"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["static_configs"] == [
        {"targets": ["backend:8000"]}
    ]


def test_public_nginx_does_not_proxy_prometheus_metrics() -> None:
    nginx = _read("docker/nginx/default.conf")

    metrics = nginx.split("location = /metrics", maxsplit=1)[1]
    metrics = metrics.split("}", maxsplit=1)[0]

    assert "return 404;" in metrics
    assert "proxy_pass" not in metrics


def test_runbook_marks_volume_deletion_as_destructive() -> None:
    runbook = _read("doc/Production_Runbook.md")

    assert "Do not use `down -v` during normal operations." in runbook
    assert "intentional full reset" in runbook
