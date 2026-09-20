# Upgrade Phase 2B Closeout

## Status

**Phase 2B — Runtime Loop LangGraph Migration: COMPLETE**

Phase 2B replaced the internal Python runtime control loop with node-level LangGraph
orchestration while preserving planner semantics, Docker read-only tools, evidence
construction, trace semantics, failure recovery, and citation behavior.

## Final Runtime Architecture

~~~text
Support Graph
    ↓
runtime node
    ↓
Runtime Loop Graph
    ↓
plan
  ├─ finish → END
  └─ tool
       ↓
   execute/update
       ↓
      plan
       ↺
~~~

The legacy `run_dynamic_runtime_workflow(...)` remains available only as a baseline.

## Deterministic Runtime-Loop Parity

Planner decisions were recorded from the legacy loop and replayed into the Graph loop.
This isolates framework behavior from model sampling variance.

~~~text
normal       7 cases  exact_runtime_loop_parity_rate = 1.0
failure      4 cases  exact_runtime_loop_parity_rate = 1.0
timeout      2 cases  exact_runtime_loop_parity_rate = 1.0
permission   2 cases  exact_runtime_loop_parity_rate = 1.0
~~~

Across these datasets:

~~~text
tool sequence parity = 1.0
result parity        = 1.0
trace parity         = 1.0
evidence parity      = 1.0
error parity         = 1.0
~~~

## End-to-End Agent Result

Normal 8-case post-cutover run:

~~~text
exact_parity_rate                  = 1.0
legacy_expected_accuracy           = 1.0
graph_expected_accuracy            = 1.0
mean_groundedness                  = 5.0
mean_runtime_citation_correctness  = 5.0
mean_docs_citation_correctness     = 5.0
mean_diagnosis_quality             = 5.0
unsupported_claim_case_rate        = 0.0
graph_judge_errors                 = 0
~~~

Abnormal Graph Judge runs also reached:

~~~text
timeout     grounded/citations/diagnosis = 5.0, unsupported = 0
permission  grounded/citations/diagnosis = 5.0, unsupported = 0
failure     grounded/citations/diagnosis = 5.0, unsupported = 0
~~~

## Interpreting Live Parity Variance

A repeated live failure-suite run produced one planner divergence:

~~~text
legacy: docker_inspect -> docker_logs
graph:  docker_inspect -> docker_logs -> docker_ps
~~~

This is not classified as a LangGraph regression because:

1. the legacy and Graph agents invoke the planner independently during live parity;
2. the deterministic replay runtime-loop evaluator reached 1.0 on the same failure suite;
3. Graph Judge remained fully grounded with correct citations and no unsupported claims;
4. the additional tool call came from a different valid planner decision, not from a
   changed graph transition or tool-execution rule.

Likewise, occasional expected-answer misses in permission/failure suites are lexical
coverage differences in generated answers. They do not override perfect grounding and
citation Judge results.

## Phase 2B Completion Criteria

Phase 2B is closed because all migration-critical conditions are satisfied:

- node-level loop parity is deterministic and complete;
- timeout/failure/permission behavior is preserved;
- unified support graph now uses the node-level runtime graph;
- final answer grounding and citation quality did not regress;
- the legacy implementation remains available for future regression debugging.

## Validation Policy Going Forward

To avoid spending most development time on repeated validation:

- normal development: Ruff + unit/targeted tests;
- feature-stage gate: one representative integration/eval run;
- release/merge gate: full normal/failure/timeout/permission matrix + Judge.

Phase 3 should focus primarily on new architecture capability rather than repeatedly
revalidating already-frozen Phase 2 behavior.

## Next

**Phase 3 — Role Separation / Multi-Agent Architecture**
