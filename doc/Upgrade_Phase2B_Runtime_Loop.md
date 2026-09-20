# Upgrade Phase 2B — Runtime Loop Graph Migration

## Status

**Step 1 / Step 2 complete; abnormal parity gate passed; support-graph cutover implemented.**

## Objective

Replace the internal legacy runtime loop:

~~~text
build evidence
→ planner
→ execute one Docker tool
→ append observation
→ planner again
~~~

with an equivalent LangGraph node loop:

~~~text
START
  ↓
plan
  ├─ finish → END
  └─ tool
       ↓
   execute/update
       ↓
   max steps?
     ├─ no  → plan
     └─ yes → error
~~~

The unified LangGraph support workflow now calls the node-level runtime loop graph.
The legacy loop remains in the codebase as the comparison baseline.

## Shared Runtime Primitives

Legacy and Graph loops now share:

~~~python
execute_runtime_tool(...)
runtime_timeout_result(...)
build_runtime_evidence(...)
plan_runtime_action(...)
~~~

This keeps Docker command dispatch, timeout conversion, planner validation, and evidence
format from drifting across two implementations.

## Unit-Level Parity Coverage

Current deterministic tests compare legacy and Graph loops for:

- direct stats flow;
- inspect → logs → finish;
- Docker tool timeout → synthetic timeout evidence;
- container-not-found → docker_ps recovery;
- logs unavailable after inspect;
- permission denied;
- finish-before-evidence safety guard;
- max-step exhaustion safety guard.

The comparison includes:

~~~text
DockerToolResult sequence
DynamicRuntimeStep trace
RuntimeEvidence text
RuntimeEvidence truncated flag
error semantics
~~~

## Normal Runtime Dataset Result

The full normal runtime subset currently reached:

~~~text
cases                              7
route_runtime_accuracy             1.0
tool_sequence_parity_rate          1.0
result_parity_rate                 1.0
trace_parity_rate                  1.0
evidence_parity_rate               1.0
error_parity_rate                  1.0
legacy_expected_tool_accuracy      1.0
graph_expected_tool_accuracy       1.0
exact_runtime_loop_parity_rate     1.0
~~~

The evaluator records planner decisions from the legacy loop and replays those exact raw
decisions into the Graph loop. This isolates framework/orchestration parity from LLM
sampling variance.

## Abnormal Scenario Gate

Before cutover, run the same evaluator on:

~~~text
dynamic_failure_v1.jsonl
dynamic_timeout_v1.jsonl
dynamic_permission_v1.jsonl
~~~

Required for each dataset:

~~~text
route_runtime_accuracy             = 1.0
tool_sequence_parity_rate          = 1.0
result_parity_rate                 = 1.0
trace_parity_rate                  = 1.0
evidence_parity_rate               = 1.0
error_parity_rate                  = 1.0
legacy_expected_tool_accuracy      = 1.0
graph_expected_tool_accuracy       = 1.0
exact_runtime_loop_parity_rate     = 1.0
~~~

## Abnormal Scenario Gate Result

All required abnormal datasets passed with every runtime-loop parity metric equal to 1.0:

~~~text
failure     4 cases  ✅
timeout     2 cases  ✅
permission  2 cases  ✅
~~~

Together with the normal 7-case result, the node-level runtime loop passed the cutover gate.

## Cutover

The LangGraph workflows now use:

~~~python
run_runtime_loop_graph(...)
~~~

instead of:

~~~python
run_dynamic_runtime_workflow(...)
~~~

for runtime execution.

The legacy implementation remains available as the baseline and is still used by the
legacy `DynamicDockerSupportAgent`.

## Final Phase 2B Gate

After cutover:

1. run Ruff and the full unit-test suite;
2. rerun Legacy-vs-LangGraph agent parity on normal;
3. rerun normal Graph Judge;
4. rerun Legacy-vs-LangGraph parity on failure / timeout / permission;
5. close Phase 2B only if end-to-end parity and answer grounding remain stable.

## Cutover End-to-End Regression Result

After switching the unified support graph to `run_runtime_loop_graph(...)`, the complete
Legacy-vs-LangGraph agent parity was rerun.

### Normal

~~~text
cases                              8
route_parity_rate                  1.0
container_ref_parity_rate          1.0
use_docs_parity_rate               1.0
tool_sequence_parity_rate          1.0
trace_parity_rate                  1.0
citation_parity_rate               1.0
clarification_parity_rate          1.0
graph_evidence_labels_match_rate   1.0
legacy_expected_accuracy           1.0
graph_expected_accuracy            1.0
exact_parity_rate                  1.0
~~~

Graph Judge:

~~~text
mean_groundedness                  5.0
mean_runtime_citation_correctness  5.0
mean_docs_citation_correctness     5.0
mean_diagnosis_quality             5.0
unsupported_claim_case_rate        0.0
graph_judge_errors                 0
~~~

### Failure / Timeout / Permission

All three abnormal suites preserved exact structural parity:

~~~text
failure     exact_parity_rate = 1.0
timeout     exact_parity_rate = 1.0
permission  exact_parity_rate = 1.0
~~~

Timeout also retained expected-answer accuracy at 1.0 for both implementations.

Failure and permission still show occasional lexical expected-answer misses in one or both
implementations while structural parity remains exact. These are not treated as migration
failures by themselves because the same routing, tools, trace, citations, clarification,
and evidence labels are preserved.

The final Phase 2B gate therefore requires abnormal Graph Judge runs before closeout.

## Final Abnormal Judge Gate

Run the parity evaluator with `--judge` for:

- `data/eval/dynamic_failure_v1.jsonl`
- `data/eval/dynamic_timeout_v1.jsonl`
- `data/eval/dynamic_permission_v1.jsonl`

Close Phase 2B if each Graph Judge reports:

~~~text
mean_groundedness                  = 5.0
mean_runtime_citation_correctness  = 5.0
mean_docs_citation_correctness     = 5.0
mean_diagnosis_quality             = 5.0
unsupported_claim_case_rate        = 0.0
graph_judge_errors                 = 0
~~~

The deterministic expected-answer metric remains diagnostic for lexical coverage; it is
not allowed to override a failing grounding/citation Judge, but it is also not used alone
to classify a framework migration as failed.
