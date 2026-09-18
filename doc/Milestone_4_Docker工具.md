# Milestone 4：Docker Tool Calling

## 目标

Milestone 3 已经证明文档 RAG 能回答知识型问题，并且在 runtime-only 测试中能够承认证据不足。

Milestone 4 开始解决这类问题：

~~~text
我本机 nginx-prod 容器现在用了多少内存？
web 容器为什么重启？
这个容器最近输出了什么错误？
~~~

这些问题不能仅依赖 Docker Docs，需要读取用户当前 Docker runtime。

第一步先实现安全、可测试的只读 Docker 工具层，不立即把任意 shell 权限交给模型。

## 第一版允许的工具

- docker info
- docker ps --all
- docker inspect CONTAINER
- docker logs --tail N CONTAINER
- docker stats --no-stream CONTAINER

暂时不提供：

- docker rm
- docker stop / kill / restart
- docker exec
- docker system prune
- docker compose down
- 任意用户提供的 shell 命令或 CLI flags

## 安全边界

实现位于：

src/docker_agent/tools/docker_cli.py

核心原则：

1. subprocess 使用 shell=False。
2. 工具函数构造固定 argv，不执行模型自由生成的完整命令。
3. container name / ID 做白名单字符校验。
4. logs 设置最大行数，避免无限日志进入上下文。
5. 所有命令设置 timeout。
6. Docker 非零退出码作为结构化结果返回，由上层 Agent 判断，不自动执行补救写操作。

这一步把“模型能做事”和“模型拥有任意终端权限”明确分开。

## 本地测试

切到新分支：

~~~powershell
git fetch origin
git checkout feat/milestone-4-docker-tools
git pull --ff-only

uv run ruff check .
uv run pytest -v
~~~

真实 Docker CLI smoke test：

~~~powershell
uv run python scripts/docker_diag.py info
uv run python scripts/docker_diag.py ps
~~~

如果存在一个测试容器：

~~~powershell
uv run python scripts/docker_diag.py inspect <container>
uv run python scripts/docker_diag.py logs <container> --tail 50
uv run python scripts/docker_diag.py stats <container>
~~~

## 下一步

工具层通过后，再增加 Agent Router：

~~~text
User Question
      ↓
Intent / evidence decision
  ┌──────────────┬───────────────┐
  │ docs enough? │ runtime needed│
  ↓              ↓
RAG only      Docker read tools
  │              │
  └──────┬───────┘
         ↓
 Docker Docs + runtime evidence
         ↓
 Grounded diagnosis
~~~

Agent 不会一开始就“自动跑一堆命令”，而是只在问题确实依赖本机状态时调用最小必要的只读工具。


## Agent Router

工具 smoke test 通过后，新增：

- `src/docker_agent/agent/router.py`
- `src/docker_agent/agent/runtime.py`
- `scripts/route_agent.py`

Router 只做“证据路径选择”，不直接回答问题。当前输出三种 route：

~~~text
docs_only
runtime_tools
clarify
~~~

典型行为：

~~~text
Docker volume 和 bind mount 有什么区别？
→ docs_only

docker-agent-postgres 现在用了多少内存？
→ runtime_tools
→ docker_stats

web 容器为什么重启？
→ runtime_tools
→ docker_inspect + docker_logs

我的容器为什么一直重启？
→ clarify
→ 先询问具体容器名
~~~

Router 的模型输出仍然不是可信输入，因此在执行之前会进行严格校验：

1. tool name 必须属于只读 allowlist。
2. `docker_restart`、`docker_rm` 等未知/写操作会被拒绝。
3. inspect/logs/stats 必须有显式 container_ref。
4. container_ref 必须通过字符白名单校验。
5. `docs_only` route 不允许夹带任何 runtime tool。

### 测试 Router，不执行命令

~~~powershell
uv run python scripts/route_agent.py "Docker volume 和 bind mount 有什么区别？"

uv run python scripts/route_agent.py "docker-agent-postgres 现在用了多少内存？"

uv run python scripts/route_agent.py "我的容器为什么一直重启？"
~~~

### 执行经过校验的只读计划

使用当前已存在的测试容器：

~~~powershell
uv run python scripts/route_agent.py "docker-agent-postgres 现在用了多少内存？" --execute
~~~

理想 route：

~~~json
{
  "route": "runtime_tools",
  "container_ref": "docker-agent-postgres",
  "tools": ["docker_stats"]
}
~~~

然后输出真实 `docker stats --no-stream` 结果。

当前仍然没有把 Docker Docs RAG 和 runtime evidence 合并成最终回答；这一层将在下一个子任务完成。


## Runtime Evidence + Docker Docs 合并回答

Router 与只读工具通过后，新增：

- `src/docker_agent/agent/evidence.py`
- `src/docker_agent/agent/answer.py`
- `scripts/ask_agent.py`

新的端到端流程：

~~~text
User Question
      ↓
Agent Router
      ↓
docs_only / runtime_tools / clarify
      ↓
runtime_tools 时执行只读 Docker tools
      ↓
构造 [R1] [R2] runtime evidence
      +
Docker Docs Retrieval + Reranker
      ↓
合并到同一个 grounded prompt
      ↓
LLM
      ↓
Runtime facts + Docker Docs guidance
~~~

引用规则：

- `[R1]`、`[R2]`：本机 Docker runtime 证据。
- `[1]`、`[2]`：Docker 官方文档证据。

Agent 必须区分“观察到的事实”和“可能解释”。

例如：

~~~text
docker-agent-postgres 当前内存使用约 64MiB。[R1]

Docker 的运行时资源统计可以通过 docker stats 查看。[1]
~~~

如果工具只证明“容器退出了”，但日志/inspect 不能证明根因，模型必须明确说根因仍不能确定。

### 本地测试

先更新：

~~~powershell
git pull --ff-only
uv run ruff check .
uv run pytest -v
~~~

测试纯文档问题：

~~~powershell
uv run python scripts/ask_agent.py "Docker volume 和 bind mount 有什么区别？"
~~~

测试真实 runtime + docs：

~~~powershell
uv run python scripts/ask_agent.py "docker-agent-postgres 现在用了多少内存？"
~~~

测试缺少容器名：

~~~powershell
uv run python scripts/ask_agent.py "我的容器为什么一直重启？"
~~~

理想行为是直接返回 clarification，不执行 Docker 命令。

还可以利用当前已经退出的测试容器进行诊断：

~~~powershell
uv run python scripts/ask_agent.py "zealous_kirch 为什么退出了？"
~~~

这类问题 Router 应优先规划 `docker_inspect` + `docker_logs`，然后结合官方文档回答。当前仍只允许读操作，不会自动 restart / rm / exec。
