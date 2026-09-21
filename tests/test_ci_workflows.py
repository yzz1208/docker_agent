import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow() -> dict[str, object]:
    text = (ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    return yaml.load(text, Loader=yaml.BaseLoader)


def test_ci_uses_read_only_permissions_and_safe_events() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow["on"]
    assert set(workflow["on"]) == {"push", "pull_request"}


def test_ci_backend_runs_lint_migration_and_tests() -> None:
    workflow = _workflow()
    backend = workflow["jobs"]["backend"]
    commands = "\n".join(
        step.get("run", "")
        for step in backend["steps"]
        if isinstance(step, dict)
    )

    assert "uv sync --all-groups" in commands
    assert "uv run ruff check ." in commands
    assert "tests/test_migrations.py" in commands
    assert "tests/test_database_runtime.py" in commands
    assert "uv run pytest -v" in commands


def test_ci_frontend_runs_typecheck_tests_and_build() -> None:
    workflow = _workflow()
    frontend = workflow["jobs"]["frontend"]
    commands = [
        step.get("run")
        for step in frontend["steps"]
        if isinstance(step, dict) and step.get("run")
    ]

    assert "npm install" in commands
    assert "npm run typecheck" in commands
    assert "npm test" in commands
    assert "npm run build" in commands


def test_ci_validates_production_compose_with_production_env() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["production-config"]
    commands = "\n".join(
        step.get("run", "")
        for step in job["steps"]
        if isinstance(step, dict)
    )

    assert "cp .env.production.example .env.production" in commands
    assert "--env-file .env.production" in commands
    assert "-f compose.prod.yaml" in commands
    assert "config" in commands


def test_ci_uses_linux_cpu_pytorch_source() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'index = "pytorch-cpu"' in pyproject
    assert 'marker = "sys_platform == \'linux\'"' in pyproject
    assert 'index = "pytorch-cu130"' in pyproject
    assert 'marker = "sys_platform == \'win32\'"' in pyproject



def test_ci_runtime_versions_match_project_contracts() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = json.loads(
        (ROOT / "web/package.json").read_text(encoding="utf-8")
    )

    assert 'required-version = ">=0.8,<1.0"' in pyproject
    assert package["engines"]["node"] == ">=22 <23"
