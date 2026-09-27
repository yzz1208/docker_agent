from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_compose_orders_migration_before_backend() -> None:
    compose = yaml.safe_load(_read("compose.prod.yaml"))
    services = compose["services"]

    assert compose["name"] == "docker-agent-prod"
    assert set(services) == {
        "postgres",
        "migrate",
        "rag-schema",
        "backend",
        "prometheus",
        "web",
    }

    assert services["migrate"]["command"] == [
        "alembic",
        "upgrade",
        "head",
    ]
    assert services["migrate"]["depends_on"]["postgres"] == {
        "condition": "service_healthy"
    }
    assert services["rag-schema"]["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }
    assert services["backend"]["depends_on"]["rag-schema"] == {
        "condition": "service_completed_successfully"
    }
    assert services["web"]["depends_on"]["backend"] == {
        "condition": "service_healthy"
    }


def test_production_compose_uses_readiness_health_and_bounded_public_ports() -> None:
    compose = yaml.safe_load(_read("compose.prod.yaml"))
    services = compose["services"]

    backend_health = " ".join(
        str(item)
        for item in services["backend"]["healthcheck"]["test"]
    )
    web_health = " ".join(
        str(item)
        for item in services["web"]["healthcheck"]["test"]
    )

    assert "/health/ready" in backend_health
    assert "/health/ready" in web_health

    assert "ports" not in services["backend"]
    assert "ports" not in services["postgres"]
    assert services["web"]["ports"] == [
        "${WEB_PORT:-8080}:8080"
    ]


def test_production_compose_does_not_mount_docker_socket_by_default() -> None:
    compose_text = _read("compose.prod.yaml")

    assert "/var/run/docker.sock" not in compose_text


def test_nginx_keeps_operations_page_in_spa_and_proxies_operations_apis() -> None:
    nginx = _read("docker/nginx/default.conf")

    assert "location = /operations/summary" in nginx
    assert "location = /operations/performance" in nginx
    assert "location ^~ /operations/runs" in nginx
    assert "location ^~ /operations/evaluations" in nginx
    assert "location = /operations {" not in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx


def test_backend_image_runs_as_non_root_application_user() -> None:
    dockerfile = _read("docker/Dockerfile.backend")

    assert "FROM python:3.12-slim AS runtime" in dockerfile
    assert "uv sync --no-dev --no-editable" in dockerfile
    assert "USER app" in dockerfile
    assert "/app/.cache/huggingface" in dockerfile
    assert '"docker_agent.main:app"' in dockerfile


def test_web_image_is_multistage_and_served_by_nginx() -> None:
    dockerfile = _read("docker/Dockerfile.web")

    assert "FROM node:22-alpine AS build" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "FROM nginx:1.27-alpine AS runtime" in dockerfile
    assert "COPY --from=build /app/dist" in dockerfile


def test_dockerignore_excludes_secrets_and_generated_artifacts() -> None:
    dockerignore = _read(".dockerignore").splitlines()

    assert ".env" in dockerignore
    assert ".venv" in dockerignore
    assert "web/node_modules" in dockerignore
    assert "web/dist" in dockerignore


def test_production_compose_bootstraps_rag_schema_without_resetting_chunks() -> None:
    compose = yaml.safe_load(_read("compose.prod.yaml"))
    command = " ".join(compose["services"]["rag-schema"]["command"])

    assert "init_vector_store" in command
    assert "clear_chunks" not in command
    assert "--reset" not in command


def test_production_compose_uses_production_env_and_requires_db_password() -> None:
    compose_text = _read("compose.prod.yaml")
    compose = yaml.safe_load(compose_text)
    backend_common = compose["x-backend-common"]

    assert backend_common["env_file"] == [".env.production"]
    assert backend_common["environment"]["TOOL_MODE"] == "mock"
    assert (
        backend_common["environment"]["ALLOW_LOCAL_DOCKER_TOOLS"]
        == "false"
    )
    assert "POSTGRES_PASSWORD:?" in compose_text
    assert "postgres:postgres" not in compose_text


def test_environment_secret_files_are_ignored_but_examples_are_tracked() -> None:
    gitignore = _read(".gitignore").splitlines()

    assert ".env" in gitignore
    assert ".env.test" in gitignore
    assert ".env.production" in gitignore
    assert (ROOT / ".env.test.example").is_file()
    assert (ROOT / ".env.production.example").is_file()


def test_prometheus_monitoring_profile_scrapes_backend_internally() -> None:
    compose = yaml.safe_load(_read("compose.prod.yaml"))
    prometheus = compose["services"]["prometheus"]
    config = yaml.safe_load(
        _read("docker/prometheus/prometheus.yml")
    )

    assert prometheus["profiles"] == ["monitoring"]
    assert prometheus["depends_on"]["backend"] == {
        "condition": "service_healthy"
    }
    assert prometheus["ports"] == [
        "${PROMETHEUS_PORT:-9090}:9090"
    ]

    scrape = config["scrape_configs"][0]
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["static_configs"][0]["targets"] == [
        "backend:8000"
    ]


def test_nginx_proxies_registered_agent_apis() -> None:
    nginx = _read("docker/nginx/default.conf")

    assert "location = /agents" in nginx
    assert "location ^~ /agents/" in nginx


def test_nginx_does_not_expose_metrics_publicly() -> None:
    nginx = _read("docker/nginx/default.conf")

    assert "location = /metrics" in nginx
    metrics_block = nginx.split("location = /metrics", maxsplit=1)[1]
    metrics_block = metrics_block.split("}", maxsplit=1)[0]
    assert "return 404;" in metrics_block
    assert "proxy_pass" not in metrics_block
