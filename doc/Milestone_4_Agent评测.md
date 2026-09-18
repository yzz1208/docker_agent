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
