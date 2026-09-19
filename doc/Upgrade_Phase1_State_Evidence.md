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


## 13. Step 5 — Shadow Mode 已实现

当前 Dynamic Workflow Eval 会在不改变最终 Answer 输入的前提下，同时构建：

~~~text
Legacy Path
DockerToolResult
  ↓
RuntimeEvidenceContext

Shadow Path
DockerToolResult
  ↓
ToolResult
  ↓
Evidence
  ↓
EvidenceBundle
  ↓
AgentState
~~~

最终回答仍然使用旧的 RuntimeEvidenceContext / RagContext，因此 Shadow Mode 不参与生产决策。

Shadow 会校验：

- runtime evidence 数量；
- citation label；
- tool/source；
- success/failure 状态；
- evidence content；
- runtime trace 的 step/action/tool/reason/ok；
- route / container_ref / use_docs；
- final answer 是否一致。

Dynamic Eval 输出新增：

~~~text
shadow=pass / fail
~~~

Summary 新增：

~~~json
{
  "shadow": {
    "cases": 8,
    "coverage_rate": 1.0,
    "pass_rate": 1.0,
    "issue_cases": []
  }
}
~~~

若 Shadow adapter 或 parity check 出错，只记录 shadow failure，不改变旧 Agent 的执行结果。这保证当前阶段可以安全观察新 Schema，而不是立即切流。

另外修正了两个兼容细节：

1. Docker error classification 同时检查 stdout + stderr，避免 partial stdout 掩盖真正的 permission/daemon 错误；
2. failed runtime Evidence 保留旧逻辑的 stdout 优先级，确保迁移时 prompt evidence 内容不发生隐式变化。

### Step 5 验证命令

~~~powershell
uv run ruff check .
uv run pytest -v
uv run python scripts/eval_dynamic_workflow.py
~~~

第一目标是：

~~~text
shadow.coverage_rate = 1.0
shadow.pass_rate     = 1.0
shadow.issue_cases   = []
~~~

然后再分别运行 failure / timeout / permission 数据集，确认异常证据同样能通过 Shadow Mode。


## 14. Step 6 — Answer Context 迁移到 Unified Evidence

Shadow Mode 在 normal / failure / timeout / permission 四组数据上全部达到：

~~~text
coverage_rate = 1.0
pass_rate     = 1.0
issue_cases   = []
~~~

因此开始将 Answer Prompt 的内部输入切换到统一 Evidence。

### 新的内部路径

~~~text
Legacy Context
RagContext / RuntimeEvidenceContext
        ↓ compatibility adapter
EvidenceBundle
        ↓
build_agent_user_prompt_from_evidence()
        ↓
LLM
        ↓
Citation Validation
~~~

外部兼容入口仍然保留：

~~~python
generate_agent_answer(
    question,
    docs_context,
    runtime_context,
    model,
)
~~~

但该函数现在只负责把旧 Context 转换为 EvidenceBundle，然后委托给：

~~~python
generate_agent_answer_from_evidence(...)
~~~

同样：

~~~python
build_agent_user_prompt(...)
~~~

现在也是 compatibility wrapper，真正构建 Prompt 的实现已经变成：

~~~python
build_agent_user_prompt_from_evidence(...)
~~~

### 当前保持不变的部分

为了避免一次迁移过多：

- AgentAnswer 的 public fields 不变；
- CitationSource / RuntimeEvidenceSource 暂时仍用于 API/source rendering；
- Citation validation 逻辑不变；
- 用户可见 [1] / [R1] 不变；
- prompt compatibility text 不变；
- Dynamic Planner / Runtime Workflow 不变；
- FastAPI response schema 不变。

也就是说：

~~~text
Prompt 输入内部结构已经迁移
但外部行为和返回结构保持兼容
~~~

### 新增验证

新增测试确认：

1. unified Evidence prompt 与 legacy wrapper prompt 完全一致；
2. evidence-native answer path 仍返回原来的 citation source objects；
3. docs/runtime EvidenceBundle 类型不能混用；
4. legacy generate_agent_answer 继续经过统一 Evidence 路径。

### Step 6 回归目标

本地先运行：

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

然后重新运行四组 Dynamic Eval，建议这次全部带 Judge：

~~~powershell
uv run python scripts/eval_dynamic_workflow.py --judge
~~~

以及 failure / timeout / permission 三组对应的 `--judge`。

目标：

- 原有 workflow 指标不回退；
- shadow.pass_rate = 1.0；
- groundedness / citation correctness / diagnosis quality 不回退；
- unsupported claims 继续为 0。

若全部通过，Upgrade Phase 1 的 schema migration 主体即可认为完成，下一步只做 Phase 1 收尾和 Baseline 对比，不立即进入 LangGraph。


## 15. Step 6 首次回归分析

Answer Context 切到 Unified Evidence 后，四组 Shadow parity 仍保持通过；已运行的 normal / failure / timeout 均为：

~~~text
shadow.coverage_rate = 1.0
shadow.pass_rate     = 1.0
shadow.issue_cases   = []
~~~

同时：

- route accuracy = 1.0；
- tool sequence accuracy = 1.0；
- finish rate = 1.0；
- no-repeat tool rate = 1.0；
- runtime/docs citation rate = 1.0。

这说明 State / Evidence / Answer Context 迁移没有改变 orchestration 或 evidence view。

本轮出现的 end-to-end 降分来自生成文本与字符串型 required_concepts 的表达差异，例如：

~~~text
database connection error
vs
connection refused

守护进程
vs
Docker daemon

代码 1
vs
ExitCode
~~~

LLM Judge 同时认为这些回答 grounded 且 citation 正确。因此评测层新增：

~~~text
exact_orchestration_accuracy
~~~

它只衡量：

- completed；
- route；
- tool sequence；
- finish；
- step limit；
- no repeated tools。

原有 `exact_dynamic_workflow_accuracy` 继续保留，作为包含 citation + deterministic concept coverage 的 legacy end-to-end 指标。

这样后续架构迁移可以区分：

~~~text
控制流是否回退
vs
回答措辞是否命中 deterministic lexical gold
~~~

同时只对明显合理的中文/英文同义表达扩充 required_concepts，不降低 groundedness 或 citation 标准。

### Judge Error 可观测性

`--judge` 之前只输出 `judge_errors` 数量。现在新增：

~~~json
{
  "judge_error_cases": [
    {
      "id": "...",
      "error": "..."
    }
  ]
}
~~~

并在运行时直接打印 `judge error=...`，方便区分网络/API/JSON judge failure 与 Agent answer failure。
