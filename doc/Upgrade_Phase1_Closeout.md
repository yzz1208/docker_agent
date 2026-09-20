# Upgrade Phase 1 Closeout

## Status

**Phase 1: State & Evidence Migration — COMPLETE**

这一阶段完成了核心 schema 升级，但没有改变现有产品入口、Router、Dynamic Planner、Docker Runtime Tool 行为或 FastAPI response schema。

## 完成项

- Unified `ToolResult`
- `ToolErrorType`
- Unified `Evidence`
- `EvidenceBundle`
- `AgentState`
- Framework-neutral `AgentStep`
- Legacy compatibility adapters
- Shadow-mode parity validation
- Unified Evidence answer path
- Orchestration / end-to-end evaluation separation
- Judge error observability

## 迁移后的内部链路

~~~text
DockerToolResult
    ↓
ToolResult
    ↓
Evidence
    ↓
EvidenceBundle
    ↓
AgentState
    ↓
Unified Evidence Answer
~~~

旧接口继续兼容：

~~~text
RagContext
RuntimeEvidenceContext
CitationSource
RuntimeEvidenceSource
AgentAnswer
~~~

它们暂时保留用于现有 RAG、API source rendering 和 compatibility boundary。

## 最终回归

### Normal Dynamic Workflow

~~~text
cases                         8
completion_rate               1.0
route_accuracy                1.0
tool_sequence_accuracy        1.0
finish_rate                   1.0
step_limit_pass_rate          1.0
no_repeat_tool_rate           1.0
runtime_citation_rate         1.0
docs_citation_rate            1.0
exact_orchestration_accuracy  1.0
shadow.coverage_rate          1.0
shadow.pass_rate              1.0
judge_errors                  0
~~~

Judge：

~~~text
mean_groundedness                  5.0
mean_runtime_citation_correctness  5.0
mean_docs_citation_correctness     5.0
mean_diagnosis_quality             5.0
unsupported_claim_case_rate        0.0
~~~

`exact_dynamic_workflow_accuracy` 仍保留为 legacy end-to-end lexical 指标。它会受 LLM 同义表达影响，因此 Phase 1 架构回归的主门槛是：

~~~text
exact_orchestration_accuracy
shadow parity
groundedness
citation correctness
unsupported claims
~~~

### Failure / Timeout / Permission

三组均已达到：

~~~text
exact_orchestration_accuracy = 1.0
shadow.coverage_rate          = 1.0
shadow.pass_rate              = 1.0
unsupported_claim_case_rate   = 0.0
judge_errors                  = 0
~~~

## Phase 1 保留的 Legacy 类型

暂不删除：

- `DockerToolResult`
- `RuntimeEvidenceContext`
- `RuntimeEvidenceSource`
- `RagContext`
- `CitationSource`
- `DynamicRuntimeStep`
- `AgentAnswer`

原因：

1. 保持当前 API / Eval / source rendering 稳定；
2. Phase 2 LangGraph Migration 先迁移 orchestration，不同时删除兼容层；
3. 等 Graph 路径稳定后再决定 legacy cleanup。

## Phase 2 前的冻结原则

Phase 2 不允许：

- 重写已经稳定的 RAG pipeline；
- 重写 Docker tool implementation；
- 改动 citation labels；
- 改动用户可见 API schema；
- 同时引入 Multi-Agent；
- 同时引入 persistence / Redis / Celery / frontend。

下一阶段只迁移 orchestration framework。

## 下一阶段

**Upgrade Phase 2: LangGraph Migration**

目标：

~~~text
现有自研 orchestration
        ↓
LangGraph graph runtime
        ↓
保持行为一致
        ↓
完整 baseline 回归
~~~

Phase 2 完成后，再开始 Supervisor / Knowledge / Runtime / Diagnosis 的职责拆分。
