from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from typing import Any

from docker_agent.rag.llm import ChatModel


@dataclass(frozen=True, slots=True)
class WorkflowJudgeResult:
    groundedness: int
    runtime_citation_correctness: int
    docs_citation_correctness: int
    diagnosis_quality: int
    unsupported_claims: tuple[str, ...]
    rationale: str


def judge_workflow_answer(
    *,
    question: str,
    answer: str,
    runtime_evidence: str,
    docs_evidence: str,
    model: ChatModel,
) -> WorkflowJudgeResult:
    """Evaluate an agent answer only against the supplied synthetic evidence."""

    raw = model.complete(
        system_prompt=(
            "You are a strict Docker Agent evaluator. Use only the supplied evidence. "
            "Return valid JSON only."
        ),
        user_prompt=(
            f"Question:\n{question}\n\n"
            f"Runtime evidence:\n{runtime_evidence or '<none>'}\n\n"
            f"Docker Docs evidence:\n{docs_evidence or '<none>'}\n\n"
            f"Agent answer:\n{answer}\n\n"
            "Return JSON with exactly these fields:\n"
            "{\n"
            '  "groundedness": 1-5,\n'
            '  "runtime_citation_correctness": 1-5,\n'
            '  "docs_citation_correctness": 1-5,\n'
            '  "diagnosis_quality": 1-5,\n'
            '  "unsupported_claims": ["brief claim", ...],\n'
            '  "rationale": "brief explanation"\n'
            "}\n\n"
            "Rubric:\n"
            "- groundedness: every material factual claim must be supported by evidence.\n"
            "- runtime_citation_correctness: [R#] citations must support nearby runtime "
            "claims. If runtime evidence is absent and no runtime citation is needed, score 5.\n"
            "- docs_citation_correctness: [#] citations must support nearby Docker guidance. "
            "If docs evidence is absent and no docs citation is needed, score 5.\n"
            "- diagnosis_quality: judge fitness for the user's task. For causal or diagnostic "
            "questions, distinguish observations, likely causes, and uncertainty, and do not "
            "reward conclusions stronger than the evidence. For direct factual or measurement "
            "questions, score 5 when the answer directly and sufficiently answers the question "
            "from evidence; do not require extra root-cause analysis or uncertainty discussion."
        ),
    )
    payload = _parse_json_object(raw)
    unsupported = payload.get("unsupported_claims", [])
    if not isinstance(unsupported, list):
        raise TypeError("unsupported_claims must be a list")

    return WorkflowJudgeResult(
        groundedness=_score(payload, "groundedness"),
        runtime_citation_correctness=_score(
            payload,
            "runtime_citation_correctness",
        ),
        docs_citation_correctness=_score(payload, "docs_citation_correctness"),
        diagnosis_quality=_score(payload, "diagnosis_quality"),
        unsupported_claims=tuple(
            str(item) for item in unsupported if str(item).strip()
        ),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def summarize_workflow_judges(
    results: list[WorkflowJudgeResult],
) -> dict[str, float | int]:
    if not results:
        return {
            "cases": 0,
            "mean_groundedness": 0.0,
            "mean_runtime_citation_correctness": 0.0,
            "mean_docs_citation_correctness": 0.0,
            "mean_diagnosis_quality": 0.0,
            "unsupported_claim_case_rate": 0.0,
        }

    return {
        "cases": len(results),
        "mean_groundedness": mean(item.groundedness for item in results),
        "mean_runtime_citation_correctness": mean(
            item.runtime_citation_correctness for item in results
        ),
        "mean_docs_citation_correctness": mean(
            item.docs_citation_correctness for item in results
        ),
        "mean_diagnosis_quality": mean(item.diagnosis_quality for item in results),
        "unsupported_claim_case_rate": mean(
            1.0 if item.unsupported_claims else 0.0 for item in results
        ),
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("Judge response must be a JSON object")
    return payload


def _score(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise ValueError(f"{field} must be an integer from 1 to 5")
    return value
