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


## 本轮实机结果与改进

真实测试已经验证：

- `docker-agent-postgres 现在用了多少内存？`
  - Router: `runtime_tools`
  - Tool: `docker_stats`
  - 成功得到约 64 MiB 的实时内存使用。
- `Docker volume 和 bind mount 有什么区别？`
  - Router: `docs_only`
  - 没有执行 runtime tool。
- `我的容器为什么一直重启？`
  - Router: `clarify`
  - 没有容器名时先追问。
- `zealous_kirch 为什么退出了？`
  - Router: `runtime_tools`
  - `docker_inspect + docker_logs` 成功定位 PostgreSQL 初始化缺少密码配置。

这轮实机测试也暴露了三个工程问题，因此继续修正：

### 1. Clarify 不应该因为模型预先列出工具而失败

之前 Router 有时会输出：

~~~text
route=clarify
tools=[docker_inspect, docker_logs]
~~~

虽然这些工具并不会执行，但严格校验会直接报错。

现在对 clarify 使用“安全归一化”：

~~~text
clarify
→ 强制 tools=[]
→ 强制 container_ref=None
→ use_docs=False
→ 只保留 clarification
~~~

因此缺少容器名时一定不会执行命令，同时也不会因为模型描述未来计划而中断对话。

### 2. Runtime-only 问题不再强制做文档检索

此前 `zealous_kirch 为什么退出了？` 已经被 logs 明确解释，但原始问题仍会检索到无关的 Docker Engine release notes。

Router 现在额外返回：

~~~json
"use_docs": true | false
~~~

对于当前内存、当前日志、已有运行时证据足以回答的根因问题，通常为 false。

这样可以：

- 减少无关文档噪声；
- 避免每次 runtime 查询都加载 BGE-M3 和 reranker；
- 降低 GPU/延迟开销；
- 让最终回答更聚焦于真实运行证据。

如果用户同时询问“为什么 + 官方如何配置/修复”，Router 可以设置 `use_docs=true`。

### 3. docker inspect 不再把完整配置直接送给模型

完整 `docker inspect` 很大，而且 `Config.Env` 可能包含密码、token 等敏感值。

现在工具仍执行只读：

~~~text
docker inspect <container>
~~~

但在送入 Agent context 前只保留诊断摘要：

- State / ExitCode / OOMKilled / Error
- StartedAt / FinishedAt
- RestartCount / RestartPolicy
- Image / Entrypoint / Cmd
- EnvKeys

环境变量只保留“变量名”，不保留变量值。

例如：

~~~text
POSTGRES_PASSWORD=secret
~~~

只会进入模型上下文为：

~~~json
"EnvKeys": ["POSTGRES_PASSWORD"]
~~~

这既保留诊断价值，也减少 secret 泄露风险。

## 下一轮验证

~~~powershell
git pull --ff-only
uv run ruff check .
uv run pytest -v

uv run python scripts/ask_agent.py "docker-agent-postgres 现在用了多少内存？"
uv run python scripts/ask_agent.py "我的容器为什么一直重启？"
uv run python scripts/ask_agent.py "zealous_kirch 为什么退出了？"
~~~

重点观察：

1. 前两个 runtime-only 问题是否不再加载 BGE-M3 / reranker。
2. clarify 是否稳定输出追问而不是 invalid route。
3. `zealous_kirch` 是否仍能利用 compact inspect + logs 判断 PostgreSQL 初始化失败。
4. 输出末尾是否不再出现无关 release notes。
5. runtime evidence 是否不再因为完整 inspect 过大而触发 context truncation。


## 多轮 Clarification Workflow

单轮 Agent 已经能在缺少容器名时返回 `clarify`，但之前用户必须重新组织完整问题。

现在新增：

- `src/docker_agent/agent/service.py`
- `src/docker_agent/agent/conversation.py`
- `scripts/chat_agent.py`

`DockerSupportAgent` 把单轮 orchestration 从 CLI 中抽离出来，负责：

~~~text
route
→ runtime tools（可选）
→ docs retrieval（可选）
→ evidence context
→ grounded answer
→ citation validation
~~~

`AgentConversation` 只保存最小必要状态：

~~~text
pending_question
~~~

它不会缓存或持久化模型生成的工具计划，也不会自动执行上一轮建议的命令。

例如：

~~~text
You: 我的容器为什么一直重启？

Agent:
请提供具体的容器名称或ID。

You: zealous_kirch

Agent:
把上一轮问题 + 本轮 clarification 合并
→ 重新经过 Router
→ 重新安全校验 container_ref
→ inspect + logs
→ 生成诊断回答
~~~

这意味着 follow-up 仍然经过完整安全边界，而不是因为“上一轮已经计划过”就跳过校验。

### 交互式测试

~~~powershell
git pull --ff-only
uv run ruff check .
uv run pytest -v

uv run python scripts/chat_agent.py
~~~

然后输入：

~~~text
我的容器为什么一直重启？
~~~

Agent 应追问容器名。

继续输入：

~~~text
zealous_kirch
~~~

Agent 应恢复上一轮意图并完成诊断。

也可以测试：

~~~text
Docker volume 和 bind mount 有什么区别？
~~~

这类问题应直接走 `docs_only`。

交互命令：

~~~text
/reset
~~~

清空当前 pending clarification。

~~~text
/exit
~~~

退出会话。

### 当前多轮范围

目前只实现“clarification continuation”，没有持久化完整聊天历史。

这是有意控制范围：

- 可以验证多轮状态机；
- 不会把整个历史无限塞进 prompt；
- 不会让旧工具结果在后续回合被误认为当前状态；
- 下一阶段再设计 session history、context compression 和 API session storage。


## FastAPI /chat 接口

CLI 多轮流程验证后，Agent orchestration 已抽取为可复用 service，并接入 FastAPI。

当前接口：

~~~text
POST /chat
DELETE /chat/{session_id}
~~~

### 第一次提问

请求：

~~~json
{
  "message": "我的容器为什么一直重启？"
}
~~~

如果缺少容器名，响应类似：

~~~json
{
  "session_id": "...",
  "session_active": true,
  "route": "clarify",
  "reason": "...",
  "use_docs": false,
  "clarification": "请提供具体的容器名称或 ID。",
  "answer": null,
  "runtime_sources": [],
  "doc_sources": []
}
~~~

客户端保留 session_id。

### Clarification follow-up

请求：

~~~json
{
  "message": "zealous_kirch",
  "session_id": "上一步返回的 session_id"
}
~~~

Agent 会恢复 pending question、重新经过 Router 和安全校验，再执行必要的只读 Docker 工具。

完成回答后：

~~~text
session_active=false
~~~

当前 session 会自动从内存中删除，防止把旧 runtime 状态长期保留为“当前事实”。

### 主动清空 pending session

~~~text
DELETE /chat/{session_id}
~~~

用于前端用户取消当前 clarification。

### 启动 API

~~~powershell
uv run uvicorn docker_agent.main:app --reload
~~~

浏览：

~~~text
http://127.0.0.1:8000/docs
~~~

可直接使用 FastAPI Swagger 测试 POST /chat。

PowerShell 也可以先用 Invoke-RestMethod 发送第一条 POST /chat，再把返回的 session_id 放入第二条 JSON 请求中。

### 当前 Session 范围

当前服务只持久化“正在等待 clarification 的问题”。

已经完成的回答不会进入长期 session history。

这是当前阶段的安全选择：

- runtime 状态容易过期；
- 不把旧日志/旧 stats 自动带到未来问题；
- session 内存有明确生命周期；
- 为后续真正的 history window / summary / persistent session store 留出独立设计空间。

下一步将增加 API 级 Agent Eval，然后设计有限窗口的 conversation history，而不是直接把所有历史消息无限拼进 prompt。
