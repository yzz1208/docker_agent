# Upgrade Phase 2：LangGraph Migration Design

## 1. 目标

Phase 2 只迁移 orchestration framework。

目标不是增加新 Agent 能力，而是把当前稳定的 route → docs/runtime → dynamic runtime workflow → answer 迁移到 LangGraph，同时保持 Phase 1 Baseline 行为不变。

Phase 2 明确不做：Multi-Agent、Supervisor/Diagnosis 拆分、MCP、long-term memory、conversation persistence、Redis/Celery、frontend、Docker write operations。

## 2. 为什么现在适合迁移

Phase 1 已经提供稳定 domain core：ToolResult、Evidence、EvidenceBundle、AgentStep、AgentState。

因此 LangGraph 只负责 Node execution、Conditional routing、State transition 和 checkpoint-ready orchestration，而不是重新定义业务数据模型。

原则：LangGraph 是运行框架，AgentState / Evidence 是领域模型。

## 3. 迁移策略

不删除当前实现。Phase 2 同时保留 Legacy DynamicDockerSupportAgent 和新的 LangGraphDockerSupportAgent。

先进行双路径对比：同一个 question 同时走 legacy dynamic agent 和 langgraph agent，比较 route、tool sequence、evidence、citations、answer quality。

只有 Graph Eval 达到 baseline 后，才考虑让 FastAPI 默认使用 LangGraph Agent。

## 4. Phase 2A：Coarse-Grained Graph

第一版 LangGraph 不拆 Dynamic Planner 内部循环。

~~~text
START
  ↓
route_node
  ├─ clarify ───────────────→ END
  ├─ docs_only ─→ docs_node ─→ answer_node ─→ END
  └─ runtime_tools
         ↓
     runtime_node
         ↓
   need docs?
      ├─ yes → docs_node → answer_node → END
      └─ no  → answer_node → END
~~~

### route_node

复用 route_question(...)。职责：读取 question；生成 AgentRouteDecision；写入 AgentState route / container_ref / use_docs。不修改 Router Prompt。

### runtime_node

第一版直接复用 run_dynamic_runtime_workflow(...)。LangGraph 先编排大节点，Dynamic Runtime 内部仍由现有 observation-driven loop 执行。

输出 ToolResult、Runtime Evidence、AgentStep trace 和 AgentState update。

### docs_node

复用现有 docs_retriever(question)，输出 Knowledge Evidence。不修改 retrieval / reranker。

### answer_node

使用 Phase 1 新路径 generate_agent_answer_from_evidence(...)。Answer 不依赖 Graph framework。

### clarify path

Router 返回 clarify 时，不执行 docs/runtime，不生成 answer，Graph 正常 END，并返回现有 clarification 字段。

## 5. Graph Runtime State

不直接把 LangGraph 内部 state 当领域模型。

建议 GraphState 包含：agent_state、decision、docs_context、runtime_context、runtime_trace、answer。

其中 AgentState = canonical domain state；GraphState = orchestration transport state。

第一版允许保留 legacy context object，用于 API compatibility、source rendering 和 baseline parity。

## 6. Phase 2A 完成标准

必须达到：ruff PASS、pytest PASS、graph route parity 1.0、graph tool sequence 1.0、graph finish 1.0、graph evidence parity 1.0、graph citation parity 1.0、graph clarification 1.0。

Normal / Failure / Timeout / Permission 要保持 exact_orchestration_accuracy=1.0，groundedness/citation 不回退，unsupported claims=0。

Phase 2A 不要求删除 legacy agent。

## 7. Phase 2B：Runtime Loop Graph 化

只有 Phase 2A 全部通过后，才迁移内部 dynamic loop。

~~~text
runtime_plan_node
      ↓
tool_node
      ↓
observation_node
      ↓
should_continue?
   ├─ yes → runtime_plan_node
   └─ no  → finish runtime
~~~

届时逐步把当前 run_dynamic_runtime_workflow() 拆成 planner node、tool execution node、observation/state update、conditional edge。

但继续复用 DynamicRuntimeDecision schema、DockerReadOnlyTools、ToolResult error classification、Evidence conversion 和 current planner prompt。

## 8. Phase 2B 防护规则

LangGraph loop 必须保留当前安全约束：max runtime steps、no repeated tool、one tool per planning step、read-only allowlist、validated container_ref、timeout as evidence、permission denied stops fan-out、daemon unavailable stops fan-out、no speculative fallback、failed tool does not crash graph。

## 9. LangGraph Dependency 策略

暂时不在设计提交里修改依赖。

真正编码 Step 1 时：查 LangGraph 当前稳定 Python package/API；加最小依赖；锁定 uv.lock；写 graph smoke test；确认 Windows + Python 3.12 本地环境可运行。

不提前引入大量 LangChain 组件。只依赖 LangGraph 所必需的包。

## 10. Phase 2 实施顺序

### Step 1 — dependency + graph skeleton

新增 src/docker_agent/graph/__init__.py、state.py、workflow.py。只实现 START → route → END，用来验证 LangGraph runtime、state 和单测。

### Step 2 — docs-only path

实现 START → route → docs → answer → END。

### Step 3 — runtime coarse path

实现 START → route → runtime(existing loop) → answer → END。

### Step 4 — runtime + docs path

支持 runtime → docs → answer，例如 restart remediation。

### Step 5 — clarification parity

迁移 clarification single-turn graph output boundary。Session manager 暂时仍使用现有实现。

### Step 6 — graph evaluation

新增 scripts/eval_langgraph_workflow.py，对比 legacy + graph。

### Step 7 — Phase 2A gate

四组 baseline 全通过后，开始 Phase 2B。

### Step 8 — dynamic loop graph migration

把 planner/tool/observation loop 搬进 Graph。

## 11. 暂时不迁移到 Graph 的组件

继续作为普通 Python service：BGE embedder、Reranker、SQLAlchemy/pgvector store、Docker CLI adapter、LLM HTTP client、Citation validation、Workflow Judge、FastAPI session manager。

LangGraph Node 调用它们即可。

## 12. 为什么不直接 Multi-Agent

当前目标是 stable graph runtime + stable state contract + stable evidence contract。

如果同时拆 Supervisor / Knowledge / Runtime / Diagnosis，会无法判断回归来自 LangGraph runtime、Agent responsibility change、prompt change、context isolation 或 tool permission change。

因此顺序固定：Phase 2 LangGraph Migration → Baseline parity → Phase 3 Role Separation / Multi-Agent。

## 13. Phase 2 最终产物

Phase 2 完成后应同时存在 Domain Core（ToolResult/Evidence/AgentState）、Graph Runtime（Route/Knowledge/Runtime Planner Tool Loop/Answer）和 Evaluation（Legacy baseline/Graph baseline/parity report）。

此时项目才适合进一步加入 Supervisor、Diagnosis Agent、Evidence Gate、checkpoint、persistent conversation 和 HITL。

## 14. 下一步

现在只进入 Phase 2 / Step 1：LangGraph dependency + minimal graph skeleton，不直接做完整 workflow。
