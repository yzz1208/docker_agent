# Milestone 5：Dynamic Agent Workflow

## 目标

Milestone 4 的 Agent 已经能够：

- 判断 docs / runtime / clarify；
- 选择安全只读工具；
- 收集 runtime evidence；
- 生成带引用的回答；
- 支持 clarification 多轮；
- 通过 Router / Workflow / Judge 评测。

但 Milestone 4 的 runtime 工具计划仍然主要是一次性决定：

~~~text
User
 ↓
Router
 ↓
inspect + logs
 ↓
一次性执行
 ↓
Answer
~~~

Milestone 5 要升级为：

~~~text
User
 ↓
Router
 ↓
Planner: 下一步做什么？
 ↓
Tool
 ↓
Observation
 ↓
Planner: 证据够了吗？
 ├─ 否 → 下一工具
 └─ 是 → finish
 ↓
Final Answer
~~~

核心是 observe → decide → act → observe。

## 第一阶段架构

当前新增：

~~~text
src/docker_agent/agent/dynamic_planner.py
src/docker_agent/agent/dynamic_workflow.py
src/docker_agent/agent/dynamic_service.py
scripts/ask_dynamic_agent.py
~~~

### Router 负责什么

Router 仍然负责：

- docs_only / runtime_tools / clarify；
- container_ref；
- use_docs。

Milestone 5 的 Dynamic Agent 不再信任 Router 一次性给出的完整 runtime tool set。

### Dynamic Planner 负责什么

Planner 每轮只能返回一个动作：

~~~json
{
  "action": "tool",
  "tool": "docker_inspect",
  "reason": "先确认容器状态"
}
~~~

或者：

~~~json
{
  "action": "finish",
  "tool": null,
  "reason": "现有证据已经足够回答"
}
~~~

每执行一次工具以后，Planner 都会看到新的 runtime evidence，再决定下一步。

## 安全边界

Dynamic Planner 仍然没有任意 shell 权限。

允许工具只有：

~~~text
docker_info
docker_ps
docker_inspect
docker_logs
docker_stats
~~~

额外限制：

1. 一次只能选择一个工具；
2. 已经使用过的工具不能重复调用；
3. container-specific tool 必须使用 Router 已验证的 container_ref；
4. Planner 不能修改或发明 container_ref；
5. 不允许 restart / rm / exec / prune 等写操作；
6. 最大 runtime steps 默认 4；
7. Planner 不能在没有任何 runtime evidence 时直接 finish。

配置：

~~~text
DYNAMIC_RUNTIME_MAX_STEPS=4
~~~

## 为什么动态规划比一次性规划更合理

例如：

~~~text
ml-job 是不是 OOMKilled？
~~~

动态过程：

~~~text
planner → docker_inspect
observation → OOMKilled=true, ExitCode=137
planner → finish
~~~

不会额外调用 logs。

而：

~~~text
web 为什么退出？
~~~

可能是：

~~~text
planner → docker_inspect
observation → ExitCode=1，但 state 没有根因
planner → docker_logs
observation → connection refused
planner → finish
~~~

第二次工具调用由第一次 observation 决定，而不是一开始就固定。

## 本地验证

切换新分支：

~~~powershell
git fetch origin
git checkout feat/milestone-5-dynamic-workflow
git pull --ff-only

uv run ruff check .
uv run pytest -v
~~~

先测试实时内存：

~~~powershell
uv run python scripts/ask_dynamic_agent.py "docker-agent-postgres 现在用了多少内存？"
~~~

理想 trace：

~~~text
Dynamic runtime trace
[1] action=tool tool=docker_stats ok
[2] action=finish tool=<finish>
~~~

然后测试已有异常容器：

~~~powershell
uv run python scripts/ask_dynamic_agent.py "zealous_kirch 为什么退出了？"
~~~

理想 trace：

~~~text
[1] docker_inspect
[2] docker_logs
[3] finish
~~~

具体是否需要 logs 应由 inspect observation 决定。

还可以测试 OOM 型问题；如果本机没有合适容器，后续会使用 synthetic dynamic workflow eval。

## 当前阶段暂不做的事情

第一阶段先不加入：

- restart / stop / rm；
- Human-in-the-loop 写操作；
- 任意 shell；
- Planner 自由生成 Docker CLI 参数；
- 无限循环；
- 自动修改配置。

先把动态只读诊断做稳定，再扩展错误恢复和受控写操作。

## 下一步

第一阶段本地 smoke test 通过后，新增 Dynamic Workflow Eval：

~~~text
Synthetic Runtime
      ↓
Planner step 1
      ↓
Observation
      ↓
Planner step 2
      ↓
...
      ↓
Final Answer
~~~

重点评估：

- 是否真的按 observation 决定下一步；
- 是否调用最少必要工具；
- 是否重复调用工具；
- 是否在最大步数内结束；
- tool failure 后能否合理恢复；
- 最终回答是否 grounded。


## 第一阶段实机结果

真实 Docker 环境已经验证两条关键动态链路。

### 当前内存查询

问题：

~~~text
docker-agent-postgres 现在用了多少内存？
~~~

实际 trace：

~~~text
[1] docker_stats
[2] finish
~~~

Planner 在拿到 40.11 MiB 的当前内存后直接结束，没有额外调用 inspect/logs。

### 退出根因诊断

问题：

~~~text
zealous_kirch 为什么退出了？
~~~

实际 trace：

~~~text
[1] docker_inspect
    → ExitCode=1，但 state 本身没有具体根因

[2] docker_logs
    → PostgreSQL 初始化失败，缺少 POSTGRES_PASSWORD

[3] finish
~~~

这验证了 Milestone 5 的核心目标：

- 第二步是否执行 logs 由第一步 observation 决定；
- 不是 Router 在一开始就强制执行完整工具列表；
- 最终回答继续使用 [R1] / [R2] runtime citations。

## Dynamic Workflow Eval v1

实机 smoke test 通过后，新增：

~~~text
data/eval/dynamic_workflow_v1.jsonl
scripts/eval_dynamic_workflow.py
src/docker_agent/agent/dynamic_evaluation.py
~~~

第一版仍然使用 synthetic runtime，因此不会操作本机 Docker。

覆盖场景：

- memory → stats → finish；
- OOM → inspect → finish；
- PostgreSQL crash → inspect → logs → finish；
- direct logs → logs → finish；
- daemon version → info → finish；
- container list → ps → finish；
- runtime diagnosis + docs remediation；
- docs-only。

新增动态指标：

- completion_rate
- route_accuracy
- tool_sequence_accuracy
- finish_rate
- step_limit_pass_rate
- no_repeat_tool_rate
- runtime_citation_rate
- docs_citation_rate
- mean_concept_coverage
- exact_dynamic_workflow_accuracy

其中 tool_sequence_accuracy 不只是检查“调用过哪些工具”，还检查顺序：

~~~text
docker_inspect → docker_logs
~~~

与：

~~~text
docker_logs → docker_inspect
~~~

会被视为不同 workflow。

### 运行

先 smoke test：

~~~powershell
uv run python scripts/eval_dynamic_workflow.py --limit 3
~~~

再完整运行：

~~~powershell
uv run python scripts/eval_dynamic_workflow.py
~~~

也支持 Judge：

~~~powershell
uv run python scripts/eval_dynamic_workflow.py --judge
~~~

输出：

~~~text
reports/dynamic_workflow_eval_latest.jsonl
~~~

下一阶段会根据 Dynamic Eval 失败 case 增加 tool failure recovery，例如 daemon unavailable、container not found 等 observation-driven recovery。
