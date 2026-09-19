# Upgrade Phase 1：State & Evidence Migration Design

## 1. 阶段目标

这一阶段只做一件事：把当前分散在 Router、RAG、Runtime、Dynamic Workflow、Answer 中的数据结构统一成稳定的 Agent State / Evidence / Tool Result 模型。

内部结构升级不等于外部行为变化。现有 Baseline Eval 必须继续通过。

暂时不做：LangGraph、Multi-Agent、MCP、前端、用户系统、Redis/Celery、写操作、新业务功能。

## 2. 当前结构盘点

### DockerToolResult

位置：src/docker_agent/tools/docker_cli.py

已有字段：tool、command、returncode、stdout、stderr。

优点：简单、稳定、已支持失败和 timeout。问题：Docker 专用、缺少统一 error category、后续 MCP/Kubernetes 工具难以直接复用。

### RuntimeEvidenceSource / RuntimeEvidenceContext

位置：src/docker_agent/agent/evidence.py

优点：支持 [R1]、上下文截断、success/error/timeout。问题：只支持 runtime，Evidence 没有统一 ID。

### CitationSource / RagContext

位置：src/docker_agent/rag/context.py

优点：文档 metadata 和 [1] citation 已稳定。问题：与 Runtime Evidence 是另一套体系。

### DynamicRuntimeStep / DynamicRuntimeResult

位置：src/docker_agent/agent/dynamic_workflow.py

优点：记录 step、decision、result。问题：还不是完整 Agent State。

## 3. Phase 1 新目录

建议新增：

~~~text
src/docker_agent/core/
├─ __init__.py
├─ tool_result.py
├─ evidence.py
└─ state.py
~~~

第一阶段继续使用 dataclass，避免同时引入 Pydantic 行为变化。LangGraph/API 边界后续再决定 Pydantic schema。

## 4. Unified ToolResult

第一版目标字段：

~~~text
ToolResult
├─ tool_name
├─ ok
├─ output
├─ error
├─ error_type
├─ metadata
└─ raw
~~~

ToolErrorType 第一版：none、timeout、not_found、permission_denied、daemon_unavailable、command_failed、unknown。

迁移方式：不删除 DockerToolResult。新增 adapter：DockerToolResult → ToolResult。当前 Docker CLI 测试保持不变。

## 5. Unified Evidence

建议第一版：

~~~text
Evidence
├─ evidence_id
├─ kind
├─ source
├─ content
├─ ok
├─ metadata
└─ citation_label
~~~

EvidenceKind 第一版：knowledge、runtime、user。

Runtime Evidence 由 ToolResult 转换；Knowledge Evidence 由 CitationSource / retrieval result 转换。

用户仍看到 [1] / [R1]，内部增加稳定 evidence_id。第一阶段不要求模型直接生成 evidence_id。

## 6. EvidenceBundle

新增统一容器：

~~~text
EvidenceBundle
├─ items: tuple[Evidence, ...]
├─ text
└─ truncated
~~~

第一阶段 RuntimeEvidenceContext 和 RagContext 都保留，并提供转换到 EvidenceBundle 的 adapter。

## 7. AgentState

第一版只表达一次 turn，不做长期 memory。

建议字段：question、route、container_ref、use_docs、tool_results、evidence、runtime_steps、answer、errors、metadata。

边界必须明确：State 是工作流状态；Evidence 是可用于推理/回答的事实；ToolResult 是工具调用结果。

暂时不加 user_id、workspace_id、conversation_id、memory、checkpoints、human_approval、agent_role、subagent_messages。

## 8. 现有类迁移策略

- DockerToolResult：保留，新增 adapter，不直接重命名。
- RuntimeEvidenceSource / RuntimeEvidenceContext：保留，作为 compatibility view。
- CitationSource / RagContext：继续服务现有 RAG，新增 converter。
- DynamicRuntimeStep：保留，AgentState 引用它。
- AgentAnswer：保留，claims/evidence_links 后续再做。

## 9. 实际编码顺序

### Step 1 — core/tool_result.py

新增 ToolResult、ToolErrorType、classify_docker_tool_error()、from_docker_tool_result()。

要求稳定区分 timeout、permission denied、container not found、daemon unavailable、ordinary command_failed。只加单元测试，不改 Agent。

### Step 2 — core/evidence.py

新增 EvidenceKind、Evidence、EvidenceBundle，以及 runtime ToolResult / CitationSource → Evidence 的转换。

### Step 3 — core/state.py

新增 AgentState。只测试 initial state、append tool result、append evidence、append runtime step。

### Step 4 — Compatibility Adapters

让 RuntimeEvidenceContext 和 RagContext 可以映射到统一 EvidenceBundle；现有 Answer 流程仍不变。

### Step 5 — Shadow Mode

Dynamic Workflow Eval 中同时构建旧 RuntimeEvidenceContext 和新 EvidenceBundle，但最终答案仍使用旧 Context。比较 source count、labels、tool names、failure status、content。

### Step 6 — Migrate Answer Context

只有 Shadow Mode 全通过后，才让 Answer Prompt 使用统一 Evidence，然后重新跑全部 Baseline Eval。

## 10. Phase 1 完成标准

必须满足：ruff/pytest 通过；Retrieval、Router、Workflow、Dynamic、Failure、Timeout、Permission Eval 不回退；Judge 不回退。

并且：DockerToolResult 仍可独立使用；ToolResult 已统一错误类型；Knowledge/Runtime 能转换成统一 Evidence；citation label 与 evidence_id 可映射；Dynamic Workflow 可生成统一 AgentState；旧 API 行为不变。

## 11. Phase 1 明确不做

LangGraph、Supervisor Agent、Diagnosis Agent、MCP、Redis、Celery、React、用户登录、长期记忆、HITL 写操作。

## 12. 下一步

Phase 1 第一项只实现 core/tool_result.py：让 Docker 的 timeout / not-found / permission-denied / daemon-unavailable / command-failed 有统一机器可读语义。
