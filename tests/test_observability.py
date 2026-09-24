import json
import logging

from docker_agent.observability import (
    JsonLogFormatter,
    MetricsRegistry,
    correlation_context,
    current_correlation,
    redact_log_text,
    resolve_request_id,
)


def test_correlation_context_nests_and_restores() -> None:
    assert current_correlation().request_id is None
    assert current_correlation().run_id is None

    with correlation_context(request_id="request-1"):
        assert current_correlation().request_id == "request-1"
        assert current_correlation().run_id is None

        with correlation_context(
            run_id="run-1",
            conversation_id="conversation-1",
        ):
            correlation = current_correlation()
            assert correlation.request_id == "request-1"
            assert correlation.run_id == "run-1"
            assert correlation.conversation_id == "conversation-1"

        correlation = current_correlation()
        assert correlation.request_id == "request-1"
        assert correlation.run_id is None
        assert correlation.conversation_id is None

    assert current_correlation().request_id is None


def test_resolve_request_id_accepts_safe_ids_and_replaces_invalid_values() -> None:
    assert resolve_request_id(" client-123 ") == "client-123"

    generated = resolve_request_id("unsafe request id with spaces")
    assert generated != "unsafe request id with spaces"
    assert len(generated) == 32
    assert generated.isalnum()


def test_structured_formatter_includes_correlation_and_redacts_secrets() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="docker_agent.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed api_key=super-secret Bearer abcdef",
        args=(),
        exc_info=None,
    )
    record.agent_status = "failed"
    record.duration_ms = 123

    with correlation_context(
        request_id="request-1",
        run_id="run-1",
        conversation_id="conversation-1",
    ):
        payload = json.loads(formatter.format(record))

    assert payload["request_id"] == "request-1"
    assert payload["run_id"] == "run-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["agent_status"] == "failed"
    assert payload["duration_ms"] == 123
    assert "super-secret" not in payload["message"]
    assert "abcdef" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_redact_log_text_covers_common_secret_forms() -> None:
    redacted = redact_log_text(
        "token=abc password:xyz sk-abcdefgh12345678"
    )

    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "sk-abcdefgh12345678" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_metrics_registry_renders_bounded_prometheus_metrics() -> None:
    registry = MetricsRegistry()
    registry.record_http_request(
        method="GET",
        route="/operations/runs/{run_id}",
        status_code=200,
    )
    registry.record_agent_run(
        status="succeeded",
        duration_ms=250,
        route="runtime_tools",
        workers=("runtime", "diagnosis"),
    )
    registry.record_agent_run(
        status="failed",
        duration_ms=1500,
        route="docs_only",
        workers=("knowledge",),
        error_type="RuntimeError",
    )
    registry.record_stage_duration(
        stage="embedding",
        duration_ms=125,
    )
    registry.record_stage_duration(
        stage="embedding",
        duration_ms=375,
    )
    registry.record_stage_duration(
        stage="rerank",
        duration_ms=900,
    )

    output = registry.render_prometheus()

    assert (
        'docker_agent_http_requests_total{method="GET",'
        'route="/operations/runs/{run_id}",status="200"} 1'
    ) in output
    assert 'docker_agent_runs_total{status="succeeded"} 1' in output
    assert 'docker_agent_runs_total{status="failed"} 1' in output
    assert (
        'docker_agent_run_failures_total{error_type="RuntimeError"} 1'
        in output
    )
    assert 'docker_agent_run_routes_total{route="runtime_tools"} 1' in output
    assert (
        'docker_agent_worker_executions_total{worker="diagnosis"} 1'
        in output
    )
    assert "docker_agent_run_duration_seconds_count 2" in output
    assert "docker_agent_run_duration_seconds_sum 1.750000" in output
    assert (
        'docker_agent_stage_duration_seconds_count{stage="embedding"} 2'
        in output
    )
    assert (
        'docker_agent_stage_duration_seconds_sum{stage="embedding"} 0.500000'
        in output
    )
    assert (
        'docker_agent_stage_duration_seconds_count{stage="rerank"} 1'
        in output
    )
