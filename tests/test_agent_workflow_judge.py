from docker_agent.agent.workflow_judge import (
    judge_workflow_answer,
    summarize_workflow_judges,
)


class FakeJudge:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "strict Docker Agent evaluator" in system_prompt
        assert "Runtime evidence" in user_prompt
        assert "direct factual or measurement questions" in user_prompt
        return (
            "```json\n"
            "{"
            '"groundedness":5,'
            '"runtime_citation_correctness":5,'
            '"docs_citation_correctness":5,'
            '"diagnosis_quality":4,'
            '"unsupported_claims":[],'
            '"rationale":"Evidence supports the answer."'
            "}\n"
            "```"
        )


def test_workflow_judge_parses_fenced_json() -> None:
    result = judge_workflow_answer(
        question="Why did web exit?",
        answer="It exited with code 1. [R1]",
        runtime_evidence='{"ExitCode":1}',
        docs_evidence="",
        model=FakeJudge(),
    )

    assert result.groundedness == 5
    assert result.runtime_citation_correctness == 5
    assert result.docs_citation_correctness == 5
    assert result.diagnosis_quality == 4
    assert result.unsupported_claims == ()


def test_workflow_judge_summary() -> None:
    result = judge_workflow_answer(
        question="Why did web exit?",
        answer="It exited with code 1. [R1]",
        runtime_evidence='{"ExitCode":1}',
        docs_evidence="",
        model=FakeJudge(),
    )

    summary = summarize_workflow_judges([result])

    assert summary["cases"] == 1
    assert summary["mean_groundedness"] == 5
    assert summary["mean_runtime_citation_correctness"] == 5
    assert summary["mean_docs_citation_correctness"] == 5
    assert summary["mean_diagnosis_quality"] == 4
    assert summary["unsupported_claim_case_rate"] == 0.0
