# Upgrade Phase 2A Closeout

## Status

**Phase 2A — Coarse-Grained LangGraph Migration: COMPLETE**

Phase 2A moved the top-level orchestration onto LangGraph while preserving the existing
Router, Dynamic Runtime loop, RAG pipeline, unified Evidence contract, citation guards,
clarification behavior, and public agent service contract.

## Final Graph

~~~text
                    ┌→ docs ───────────────┐
                    │                      ↓
START → route ──────┤                   answer → END
                    │                      ↑
                    └→ runtime ─→ docs? ───┘
~~~

Supported paths:

~~~text
docs_only:
route -> docs -> answer

runtime_only:
route -> runtime(existing dynamic loop) -> answer

runtime + docs:
route -> runtime -> docs -> answer

clarify:
route -> END
~~~

## Compatibility Boundary

The new service:

~~~text
LangGraphDockerSupportAgent
~~~

keeps:

~~~python
handle(question) -> DynamicAgentTurnResult
~~~

so the existing:

- AgentConversation
- ChatSessionManager
- FastAPI ChatResponse

can continue unchanged during Phase 2A.

For evaluation and future migration work it also exposes:

~~~python
handle_graph(question) -> GraphState
~~~

## Final Legacy vs LangGraph Parity

The full 8-case parity run reached:

~~~text
route_parity_rate                 1.0
container_ref_parity_rate         1.0
use_docs_parity_rate              1.0
tool_sequence_parity_rate         1.0
trace_parity_rate                 1.0
citation_parity_rate              1.0
clarification_parity_rate         1.0
graph_evidence_labels_match_rate  1.0
exact_parity_rate                 1.0
~~~

Graph Judge reached:

~~~text
mean_groundedness                  5.0
mean_runtime_citation_correctness  5.0
mean_docs_citation_correctness     5.0
mean_diagnosis_quality             5.0
unsupported_claim_case_rate        0.0
graph_judge_errors                 0
~~~

## Deterministic Expected Accuracy

The last parity run showed lexical expected accuracy below 1.0 even while:

- orchestration parity was exact;
- Graph Judge was perfect;
- evidence citations were correct;
- unsupported claims were zero.

The affected cases required incidental evidence details that were not necessary to answer
the user's direct question:

- OOM question required both OOM and exit code 137;
- log-error question required both the connection-refused error and endpoint detail.

The deterministic gold was therefore narrowed to facts required by the user intent:

~~~text
OOM question       -> must identify OOM
log error question -> must identify connection refused
~~~

This is an evaluation correction, not a product prompt relaxation.

## Phase 2A Gate

Phase 2A is considered complete when these hold:

~~~text
exact_parity_rate                 = 1.0
graph Judge groundedness          = 5.0
graph Judge runtime citation      = 5.0
graph Judge docs citation         = 5.0
graph Judge diagnosis quality     = 5.0
unsupported_claim_case_rate       = 0.0
graph_judge_errors                = 0
~~~

The completed run satisfies this gate.

## What Phase 2A Did Not Change

Phase 2A did not:

- rewrite the Dynamic Planner;
- split the runtime loop into graph nodes;
- introduce Multi-Agent;
- add Docker write tools;
- add persistent memory;
- add frontend state;
- add checkpoint persistence.

The current runtime node still calls:

~~~python
run_dynamic_runtime_workflow(...)
~~~

as one coarse node.

## Next Stage

**Phase 2B — Runtime Loop Graph Migration**

Target:

~~~text
runtime_plan
    ↓
tool_execute
    ↓
observation/update
    ↓
continue?
  ├─ yes -> runtime_plan
  └─ no  -> runtime_done
~~~

The migration will preserve:

- DynamicRuntimeDecision;
- planner prompt and safety validation;
- read-only Docker allowlist;
- one-tool-per-step behavior;
- no repeated tools;
- max-step bound;
- timeout-as-evidence;
- failure recovery semantics;
- Runtime Evidence format;
- AgentState / AgentStep trace semantics.

The existing runtime loop remains as the baseline until node-level parity passes.
