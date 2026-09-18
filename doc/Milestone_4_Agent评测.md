# Milestone 4：Agent Router Evaluation v1

## 目标

前面的 Retrieval Eval 和 Answer Eval 已经分别验证了：

- 能不能找到正确资料；
- 回答是否 grounded、引用是否合理。

进入 Agent 阶段以后，还需要单独验证：

- 是否把知识型问题送到 docs_only；
- 是否把实时状态问题送到 runtime_tools；
- 是否选择了正确的只读 Docker 工具；
- 是否提取了正确的 container_ref；
- 缺少容器名时是否主动 clarify；
- runtime-only 问题是否避免无意义的 docs retrieval；
- 需要“运行时诊断 + 官方修复建议”时是否保留 use_docs=true；
- Router 输出是否合法、有没有被安全校验拦截。

这一版评测只测试 Router，不执行任何 Docker 命令，因此可以反复运行。

## 数据集

文件：

~~~text
data/eval/agent_router_v1.jsonl
~~~

第一版共 24 个初始问题，覆盖：

- docs_only：volume/bind mount、Compose healthcheck、多阶段构建、远程 daemon、环境变量优先级、内存限制；
- runtime_tools：当前 CPU/内存、退出原因、日志、容器状态、容器列表、daemon 状态、Server 版本、OOM、restart policy；
- runtime + docs：先检查具体容器，再给官方 remediation；
- clarify：没有容器名的重启、内存、日志、OOM、状态问题；
- clarification follow-up：第二轮只补充容器名后，重新检查 Router 是否恢复原意图。

## 指标

当前 Summary 包含：

- safe_decision_rate
  - Router 输出通过 JSON / allowlist / container_ref 等程序校验的比例。
- route_accuracy
  - docs_only / runtime_tools / clarify 是否正确。
- tool_exact_match_accuracy
  - 工具集合是否与人工标注完全一致。
- container_ref_accuracy
  - 是否提取到正确容器名/ID，且没有凭空发明。
- use_docs_accuracy
  - 是否正确决定需要或不需要 Docker Docs。
- clarification_accuracy
  - 需要 clarify 时是否真正给出 clarification；不需要时是否没有多余 clarification。
- exact_plan_accuracy
  - route、tools、container_ref、use_docs、clarification 全部同时正确。

还会分别统计 initial 和 follow_up。

## 运行

先同步和跑测试：

~~~powershell
git pull --ff-only
uv run ruff check .
uv run pytest -v
~~~

先跑 5 条 smoke test：

~~~powershell
uv run python scripts/eval_agent_router.py --limit 5
~~~

然后跑完整 v1：

~~~powershell
uv run python scripts/eval_agent_router.py
~~~

结果保存到：

~~~text
reports/agent_router_eval_latest.jsonl
~~~

reports 已被 gitignore。

## 稳定性测试

即使 temperature=0，部分远程模型服务仍可能存在轻微非确定性。

可以重复三次：

~~~powershell
uv run python scripts/eval_agent_router.py --repeats 3
~~~

这时每个 case 会运行三次，用来观察 exact plan 是否稳定。

注意：这里仍然不会执行 docker inspect / logs / stats，只调用 Router 模型。

## 如何分析失败

### route 错误

例如：

~~~text
expected=clarify
actual=runtime_tools
~~~

需要检查 Router 是否在缺少 container_ref 时仍试图执行 container-specific tool。

### tool_exact_match 错误

例如：

~~~text
expected=[docker_inspect, docker_logs]
actual=[docker_logs]
~~~

说明模型知道要查 runtime，但计划缺少必要证据。

### use_docs 错误

例如当前内存问题：

~~~text
expected use_docs=false
actual use_docs=true
~~~

虽然不一定造成错误回答，但会增加 BGE-M3 / reranker 延迟和无关文档噪声。

反过来：

~~~text
“web 为什么一直重启？检查以后告诉我官方怎么配置 restart policy”
~~~

这里 expected use_docs=true，因为除了 runtime diagnosis，还明确要求官方配置建议。

### validation block

如果 Router 输出 docker_restart、docker_rm、虚构 container_ref、非法 JSON 等，会被 AgentRoutingError 拦截。

这在安全上比实际执行危险计划更好，但在 Agent Eval 中仍记为失败，需要继续改进 Router。

## 与单元测试的区别

单元测试验证“程序安全边界一定工作”，例如：

- docker_restart 一定被拒绝；
- 没有 container_ref 时 docker_logs 一定不能执行；
- clarify 一定会清空工具计划。

Agent Router Eval 验证的是：

> 真实 LLM 在这些问题上能不能稳定地产生正确计划。

两者缺一不可。

## 下一步

Router Eval 稳定后，进入第二层 Agent Eval：

~~~text
Synthetic / Mock Runtime Scenarios
           ↓
Router
           ↓
Read-only Tool Execution
           ↓
Runtime Evidence
           ↓
Final Agent Answer
           ↓
Tool choice + grounded diagnosis + citation evaluation
~~~

这样可以在不依赖某台真实机器当前容器状态的情况下，重复评测完整 Agent workflow。


## 当前 Router Eval 实测结果

首次完整运行：

~~~json
{
  "attempts": 30,
  "safe_decision_rate": 1.0,
  "route_accuracy": 1.0,
  "tool_exact_match_accuracy": 0.9667,
  "container_ref_accuracy": 1.0,
  "use_docs_accuracy": 1.0,
  "clarification_accuracy": 1.0,
  "exact_plan_accuracy": 0.9667
}
~~~

其中 follow-up 6/6 全部通过。

这说明 Router 的核心边界已经比较稳定：

- 没有非法/危险计划；
- route 全部正确；
- container_ref 全部正确；
- docs/runtime 选择全部正确；
- clarification 全部正确。

唯一剩余误差来自 1 次 tool exact mismatch。

评测脚本现在会在失败时直接打印 expected / actual plan，因此不需要手工打开 JSONL 才能定位。

重新运行：

~~~powershell
uv run python scripts/eval_agent_router.py
~~~

如果出现 plan=false，会额外显示：

~~~text
expected:
  tools=[...]
actual:
  tools=[...]
  reason=...
~~~

先确认这是 Router 漏工具、加了冗余工具，还是人工标注本身过于严格，再决定是否调整 Prompt。

## Full Agent Workflow Eval v1

Router 指标已经足够稳定，因此下一步增加“完整 Agent workflow”的可重复评测。

文件：

~~~text
data/eval/agent_workflow_v1.jsonl
scripts/eval_agent_workflow.py
~~~

这一层与 Router Eval 不同：

~~~text
真实 Router LLM
      ↓
Synthetic Docker Runtime
      ↓
实际 execute_runtime_plan
      ↓
Runtime Evidence Builder
      ↓
Synthetic Docs Evidence（需要时）
      ↓
真实 Answer LLM
      ↓
最终 Agent Answer
~~~

关键点：Synthetic Docker Runtime 不会调用用户本机 Docker。

例如 OOM scenario 人工固定为：

~~~text
container=ml-job
OOMKilled=true
ExitCode=137
~~~

无论用户电脑此刻有没有 ml-job，都可以重复得到相同证据。

第一版场景包括：

- 当前内存；
- OOMKilled + exit 137；
- PostgreSQL 缺少 POSTGRES_PASSWORD 导致退出；
- 日志 connection refused；
- 当前 Docker Server 版本；
- 当前容器列表；
- runtime diagnosis + Docker Docs restart policy；
- docs-only volume / bind mount。

### Workflow 指标

- completion_rate
- route_accuracy
- tool_call_exact_match_accuracy
- runtime_citation_rate
- docs_citation_rate
- mean_concept_coverage
- exact_workflow_accuracy

exact_workflow_accuracy 要求：

~~~text
完成回答
+
route 正确
+
实际调用工具正确
+
需要 runtime 时存在 [R] 引用
+
需要 docs 时存在 [n] 引用
+
关键概念全部覆盖
~~~

### 运行

先 smoke test：

~~~powershell
uv run python scripts/eval_agent_workflow.py --limit 3
~~~

确认后完整运行：

~~~powershell
uv run python scripts/eval_agent_workflow.py
~~~

结果：

~~~text
reports/agent_workflow_eval_latest.jsonl
~~~

这一层的 docs evidence 也是 synthetic，因此它刻意不重复测试 Retrieval。

评测职责现在拆成：

~~~text
Retrieval Eval
→ 文档有没有检索对

Answer Eval
→ 文档回答是否 grounded

Router Eval
→ Agent 有没有选对 evidence path / tools

Workflow Eval
→ 工具执行到最终回答的完整链路是否正确
~~~

下一阶段再把 synthetic workflow 的最终答案接入 Judge，评估 unsupported claims、runtime citation correctness 和 diagnosis quality。


## Full Workflow Eval 首次实测结果

首次完整 8 case 运行：

~~~json
{
  "completion_rate": 1.0,
  "route_accuracy": 1.0,
  "tool_call_exact_match_accuracy": 0.875,
  "runtime_citation_rate": 1.0,
  "docs_citation_rate": 1.0,
  "mean_concept_coverage": 0.8958,
  "exact_workflow_accuracy": 0.625
}
~~~

解释：

- 8/8 都成功完成回答；
- 8/8 route 正确；
- runtime/docs 引用覆盖全部正确；
- 7/8 实际工具集合与人工预期完全一致；
- 5/8 满足完整 exact workflow；
- 当前主要误差已经从“路由/安全”转移到“工具计划细节 + 回答完整性”。

因此暂时不应该为了 exact_workflow=0.625 就直接改 Router Prompt。

先区分两类失败：

1. tool mismatch：
   - Router 漏工具；
   - Router 多调用了一个合理但非必要的只读工具；
   - 人工 gold tool set 是否过严。
2. concept coverage：
   - Answer 真的遗漏重要结论；
   - 只是用了同义表达而字符串规则没命中；
   - required_concepts 标注是否需要增加合理同义词。

评测脚本已增加 missing concepts 输出，下一次失败会直接显示：

~~~text
missing concepts=[...]
~~~

同时 Router Eval 也会输出 expected / actual plan diff。

## Optional Agent Workflow Judge

字符串级 concept coverage 不能判断：

- 一句话是否真的被 runtime evidence 支持；
- [R1] 是否支持附近的事实；
- Docker Docs [1] 是否支持配置建议；
- Root-cause 结论是否强于现有证据；
- 模型是否产生 unsupported claim。

因此 Full Workflow Eval 现在支持：

~~~powershell
uv run python scripts/eval_agent_workflow.py --judge
~~~

Judge 只依据 synthetic runtime + synthetic docs evidence，输出：

- groundedness：1-5
- runtime_citation_correctness：1-5
- docs_citation_correctness：1-5
- diagnosis_quality：1-5
- unsupported_claims
- rationale

Summary 额外包含：

~~~text
mean_groundedness
mean_runtime_citation_correctness
mean_docs_citation_correctness
mean_diagnosis_quality
unsupported_claim_case_rate
~~~

当前 Judge 默认仍使用已配置模型，因此只作为诊断信号，不替代 deterministic metrics 或人工抽查。
