from docker_agent.rag.answer import GroundedAnswer
from docker_agent.rag.answer_evaluation import (
    AnswerEvalCase,
    evaluate_answer_deterministically,
    judge_answer,
    summarize_deterministic_metrics,
    summarize_judge_results,
)
from docker_agent.rag.context import CitationSource, RagContext


def _source(index: int, file_path: str) -> CitationSource:
    return CitationSource(
        index=index,
        chunk_id=f"chunk-{index}",
        title=f"Source {index}",
        section_path=("Example",),
        source_url=f"https://docs.docker.com/{index}/",
        file_path=file_path,
    )


def _answer() -> GroundedAnswer:
    sources = (
        _source(1, "expected.md"),
        _source(2, "other.md"),
    )
    return GroundedAnswer(
        answer="Use service_healthy together with a healthcheck. [1]",
        sources=sources,
        cited_sources=(sources[0],),
        citation_indices=(1,),
        context_truncated=False,
    )


class FakeJudge:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "strict RAG evaluator" in system_prompt
        assert "Generated answer" in user_prompt
        return (
            "```json\n"
            "{"
            '"groundedness":5,'
            '"citation_correctness":5,'
            '"completeness":4,'
            '"insufficient_evidence_handling":"not_applicable",'
            '"unsupported_claims":[],'
            '"rationale":"Supported by source 1."'
            "}\n"
            "```"
        )


def test_deterministic_answer_metrics_track_sources_and_concepts() -> None:
    case = AnswerEvalCase(
        case_id="compose",
        question="question",
        answerable=True,
        expected_file_paths=frozenset({"expected.md"}),
        required_concept_groups=(("service_healthy",), ("healthcheck",)),
    )

    metrics = evaluate_answer_deterministically(case, _answer())

    assert metrics.citations_present is True
    assert metrics.cited_source_count == 1
    assert metrics.retrieved_expected_source_hit is True
    assert metrics.cited_expected_source_hit is True
    assert metrics.expected_source_recall == 1.0
    assert metrics.concept_coverage == 1.0


def test_deterministic_answer_metrics_handle_unanswerable_case() -> None:
    case = AnswerEvalCase(
        case_id="runtime",
        question="current memory?",
        answerable=False,
    )

    metrics = evaluate_answer_deterministically(case, _answer())

    assert metrics.retrieved_expected_source_hit is None
    assert metrics.cited_expected_source_hit is None
    assert metrics.expected_source_recall is None


def test_judge_answer_parses_fenced_json() -> None:
    case = AnswerEvalCase(
        case_id="compose",
        question="question",
        answerable=True,
        expected_file_paths=frozenset({"expected.md"}),
    )
    context = RagContext(
        text="[1] evidence",
        sources=(_source(1, "expected.md"),),
        truncated=False,
    )

    judged = judge_answer(case, _answer(), context, FakeJudge())

    assert judged.groundedness == 5
    assert judged.citation_correctness == 5
    assert judged.completeness == 4
    assert judged.insufficient_evidence_handling == "not_applicable"
    assert judged.unsupported_claims == ()


def test_summaries_average_deterministic_and_judge_metrics() -> None:
    case = AnswerEvalCase(
        case_id="compose",
        question="question",
        answerable=True,
        expected_file_paths=frozenset({"expected.md"}),
        required_concept_groups=(("service_healthy",),),
    )
    deterministic = evaluate_answer_deterministically(case, _answer())
    context = RagContext(
        text="[1] evidence",
        sources=(_source(1, "expected.md"),),
        truncated=False,
    )
    judged = judge_answer(case, _answer(), context, FakeJudge())

    deterministic_summary = summarize_deterministic_metrics([deterministic])
    judge_summary = summarize_judge_results([judged])

    assert deterministic_summary["citation_presence_rate"] == 1.0
    assert deterministic_summary["cited_expected_source_hit_rate"] == 1.0
    assert deterministic_summary["mean_concept_coverage"] == 1.0
    assert judge_summary["mean_groundedness"] == 5
    assert judge_summary["mean_citation_correctness"] == 5
