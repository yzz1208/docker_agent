from __future__ import annotations

from dataclasses import dataclass

from docker_agent.tools.docker_cli import DockerToolResult


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceSource:
    index: int
    tool: str
    command: tuple[str, ...]
    ok: bool


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceContext:
    text: str
    sources: tuple[RuntimeEvidenceSource, ...]
    truncated: bool


def build_runtime_evidence(
    results: tuple[DockerToolResult, ...],
    *,
    max_chars: int = 8_000,
) -> RuntimeEvidenceContext:
    """Build bounded runtime evidence blocks labelled as [R1], [R2], and so on."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not results:
        return RuntimeEvidenceContext(text="", sources=(), truncated=False)

    separator = "\n\n---\n\n"
    blocks: list[str] = []
    sources: list[RuntimeEvidenceSource] = []
    truncated = False
    used_chars = 0

    for result in results:
        index = len(sources) + 1
        if result.ok:
            status = "success"
        elif result.returncode == 124 and "timed out" in result.output.casefold():
            status = "timeout"
        else:
            status = f"error(returncode={result.returncode})"
        command = " ".join(result.command)
        prefix = (
            f"[R{index}]\n"
            f"Tool: {result.tool}\n"
            f"Command: {command}\n"
            f"Status: {status}\n"
            "Output:\n"
        )

        separator_cost = len(separator) if blocks else 0
        remaining = max_chars - used_chars - separator_cost
        if remaining <= len(prefix):
            truncated = True
            break

        output = result.output.strip() or "<no output>"
        allowed_output = remaining - len(prefix)
        if len(output) > allowed_output:
            output = output[:allowed_output].rstrip()
            truncated = True

        block = prefix + output
        blocks.append(block)
        used_chars += separator_cost + len(block)
        sources.append(
            RuntimeEvidenceSource(
                index=index,
                tool=result.tool,
                command=result.command,
                ok=result.ok,
            )
        )

        if truncated:
            break

    return RuntimeEvidenceContext(
        text=separator.join(blocks),
        sources=tuple(sources),
        truncated=truncated,
    )
