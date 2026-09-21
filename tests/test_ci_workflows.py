import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str = "ci.yml") -> dict[str, object]:
    text = (ROOT / ".github/workflows" / name).read_text(
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



def test_evaluation_gate_is_manual_and_read_only() -> None:
    workflow = _workflow("evaluation-gate.yml")

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request" not in workflow["on"]
    assert "push" not in workflow["on"]


def test_evaluation_gate_requires_baseline_and_runs_persisted_candidate() -> None:
    workflow = _workflow("evaluation-gate.yml")
    dispatch = workflow["on"]["workflow_dispatch"]
    inputs = dispatch["inputs"]

    assert inputs["suite"]["type"] == "choice"
    assert inputs["baseline_run_id"]["required"] == "true"
    assert inputs["repeats"]["default"] == "1"

    job = workflow["jobs"]["evaluate"]
    commands = "\n".join(
        step.get("run", "")
        for step in job["steps"]
        if isinstance(step, dict)
    )

    assert "--persist --summary-output reports/evaluation-summary.json" in commands
    assert "scripts/eval_agent_router.py" in commands
    assert '--repeats "$ROUTER_REPEATS"' in commands
    assert "scripts/eval_agent_workflow.py" in commands
    assert "candidate_run_id" in commands
    assert "scripts/compare_evaluations.py" in commands
    assert "--output reports/evaluation-comparison.json" in commands


def test_evaluation_gate_uses_secrets_without_embedding_values() -> None:
    workflow_text = (
        ROOT / ".github/workflows/evaluation-gate.yml"
    ).read_text(encoding="utf-8")

    assert "secrets.EVALUATION_DATABASE_URL" in workflow_text
    assert "secrets.EVALUATION_MODEL_BASE_URL" in workflow_text
    assert "secrets.EVALUATION_MODEL_API_KEY" in workflow_text
    assert "vars.EVALUATION_MODEL_NAME" in workflow_text
    assert "pull_request_target" not in workflow_text


def test_persisted_evaluators_require_migrated_database() -> None:
    for script_name in (
        "eval_agent_router.py",
        "eval_agent_workflow.py",
    ):
        script = (ROOT / "scripts" / script_name).read_text(
            encoding="utf-8"
        )

        assert "require_database_ready(engine)" in script
        assert "init_persistence_store" not in script
        assert "--summary-output" in script
