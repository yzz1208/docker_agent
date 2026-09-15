# Docker Support Agent 开发文档

> 项目定位：基于 Docker 官方开源文档构建一个“会检索、会判断、会调用工具、会追问、会生成故障排查方案”的技术支持 Agent。  
> 目标用途：个人学习、作品集、简历项目、Agent / LLM 应用开发岗位面试展示。  
> 当前版本：v1.0（规划稿）  
> 建议开发周期：4～6 周（每天 1～3 小时）

---

# 1. 项目概述

## 1.1 项目名称

**Docker Support Agent**  
中文名：**基于 RAG 与工具调用的 Docker 智能技术支持 Agent**

## 1.2 项目背景

普通知识库问答系统通常只能完成：

> 用户提问 → 检索文档 → LLM 生成答案

但真实技术支持场景往往需要更复杂的行为，例如：

- 判断问题属于安装、网络、容器运行、镜像、存储还是 Compose；
- 判断当前信息是否足够；
- 必要时向用户追问操作系统、Docker 版本、错误信息；
- 查询 Docker 官方文档；
- 调用工具读取运行状态、日志、容器信息；
- 根据工具结果继续推理；
- 无法解决时生成工单或问题摘要；
- 输出可追溯到官方文档的引用来源。

因此，本项目将从简单 RAG 逐步发展为一个具备 **Retrieval + Tool Calling + Workflow + State + Evaluation** 的完整 Agent 系统。

---

# 2. 项目目标与非目标

## 2.1 核心目标

项目最终应具备以下能力：

1. **Docker 官方文档知识库**
   - 自动下载 Docker Docs 开源仓库；
   - 选择指定文档范围；
   - 清洗 Markdown；
   - 按标题与语义切分；
   - 建立向量索引；
   - 保留来源元数据。

2. **RAG 问答**
   - 用户可使用中文或英文提问；
   - 系统检索英文 Docker 官方文档；
   - 生成中文或英文答案；
   - 返回文档来源与引用片段。

3. **Agent 决策**
   - 判断是否需要检索；
   - 判断是否需要调用工具；
   - 判断用户信息是否不足；
   - 必要时主动追问；
   - 处理工具失败与重试；
   - 必要时生成工单。

4. **工具调用**
   - Docker 版本查询；
   - Docker daemon 状态查询；
   - 容器列表查询；
   - 容器 inspect；
   - 容器日志获取；
   - 磁盘占用检查；
   - 工单创建。

5. **多轮会话**
   - 保存用户已经提供的信息；
   - 保存 Agent 的诊断上下文；
   - 防止重复询问；
   - 支持同一故障的连续排查。

6. **评测体系**
   - 检索召回率；
   - 工具选择准确率；
   - 工具参数准确率；
   - 最终答案质量；
   - 端到端任务成功率。

## 2.2 非目标

第一版不做：

- Kubernetes；
- 真正的生产服务器远程控制；
- 自动执行高风险 Docker 命令；
- 多 Agent 协作；
- 复杂权限系统；
- 大规模 SaaS；
- 语音交互；
- 自动修改 Docker 配置；
- 自动删除容器、镜像、Volume。

这些功能可以作为后续扩展，而不是第一阶段目标。

---

# 3. 项目使用场景

## 3.1 文档问答

用户：

> Docker volume 和 bind mount 有什么区别？

系统：

1. 判断属于知识问答；
2. 检索 Docker 官方文档；
3. 返回答案；
4. 附带引用来源。

---

## 3.2 故障诊断

用户：

> Cannot connect to the Docker daemon，怎么回事？

系统：

1. 判断为 daemon 故障；
2. 检索 daemon troubleshooting；
3. 发现可能原因包括 daemon 未运行、DOCKER_HOST 配置错误等；
4. 如果本地 Docker 环境可访问，调用 `check_daemon_status`；
5. 根据结果生成排查步骤。

---

## 3.3 信息不足主动追问

用户：

> 我的 Docker 启动不了。

系统不应该直接猜测，而应该询问：

- 使用的操作系统；
- Docker Engine 还是 Docker Desktop；
- Docker 版本；
- 具体错误信息。

用户补充信息后继续执行诊断。

---

## 3.4 容器异常退出

用户：

> api-server 容器为什么启动后马上退出？

Agent：

1. 调用 `list_containers`；
2. 找到 `api-server`；
3. 调用 `inspect_container`；
4. 获取 exit code；
5. 调用 `get_container_logs`；
6. 必要时检索官方文档；
7. 综合工具结果和文档给出诊断。

---

## 3.5 工单升级

如果多轮诊断仍不能确定原因：

> 是否需要帮你生成一份技术支持工单摘要？

系统生成：

- 用户问题；
- 系统环境；
- Docker 版本；
- 已执行检查；
- 关键日志；
- 已尝试方案；
- 推荐下一步操作。

---

# 4. 数据来源

## 4.1 主数据源

第一阶段只使用：

**Docker 官方文档开源仓库**

仓库：

```text
https://github.com/docker/docs
```

Docker 官方说明该仓库是 Docker Documentation 网站的源代码仓库，主要内容为 Markdown，并采用 Apache License 2.0。

推荐通过 Git 获取：

```bash
git clone --depth 1 https://github.com/docker/docs.git data/raw/docker-docs
```

不要一开始导入整个仓库。

## 4.2 第一版建议文档范围

优先选择：

```text
content/get-started/
content/manuals/engine/
content/manuals/compose/
```

重点关注：

```text
daemon
container
network
storage
volume
image
registry
logs
resource constraints
install
compose
troubleshoot
```

第一版目标不是“文档越多越好”，而是构建一个质量可控的小型知识库。

## 4.3 暂不使用的数据

V1 不建议引入：

- Stack Overflow；
- Reddit；
- 博客文章；
- 非官方教程；
- GitHub Issue；
- Docker Community Forum。

原因：

1. 信息质量不稳定；
2. 版本可能过期；
3. 训练/评测时难以判断标准答案；
4. 会降低 RAG 实验的可解释性。

V2 可以再加入 GitHub Issue，构建“官方文档 + 社区案例”的双源知识库。

---

# 5. 数据目录设计

```text
data/
├── raw/
│   └── docker-docs/
│
├── selected/
│   └── markdown/
│
├── processed/
│   ├── documents.jsonl
│   └── chunks.jsonl
│
├── eval/
│   ├── retrieval_eval.jsonl
│   ├── tool_eval.jsonl
│   └── agent_eval.jsonl
│
└── mock/
    ├── hosts.json
    ├── containers.json
    └── tickets.json
```

含义：

### raw

Git clone 得到的原始 Docker 文档。

### selected

筛选后的目标 Markdown。

### processed

清洗后的 document 与 chunk。

### eval

评测数据。

### mock

没有真实 Docker 环境时，用于模拟工具调用的数据。

---

# 6. 文档数据模型

## 6.1 Document

```json
{
  "document_id": "docker_engine_daemon_troubleshoot",
  "source": "docker_docs",
  "file_path": "content/manuals/engine/daemon/troubleshoot.md",
  "title": "Troubleshooting the Docker daemon",
  "url": "https://docs.docker.com/engine/daemon/troubleshoot/",
  "language": "en",
  "content": "...",
  "updated_at": null
}
```

## 6.2 Chunk

```json
{
  "chunk_id": "docker_engine_daemon_troubleshoot__unable_connect__001",
  "document_id": "docker_engine_daemon_troubleshoot",
  "title": "Troubleshooting the Docker daemon",
  "section_path": [
    "Daemon",
    "Unable to connect to the Docker daemon"
  ],
  "content": "...",
  "source_url": "https://docs.docker.com/engine/daemon/troubleshoot/",
  "file_path": "content/manuals/engine/daemon/troubleshoot.md",
  "token_count": 320
}
```

必须保留：

- document_id
- chunk_id
- title
- section_path
- source_url
- file_path
- content

否则后续很难做好引用、调试和评测。

---

# 7. Markdown 清洗方案

Docker Docs 中可能包含：

- YAML front matter；
- Hugo shortcode；
- tabs；
- note；
- warning；
- include；
- HTML；
- 图片；
- 代码块。

## 7.1 V1 清洗原则

保留：

- 标题；
- 正文；
- 列表；
- 命令；
- 代码块；
- NOTE / WARNING 中的文本内容。

删除：

- 页面导航；
- 图片路径；
- 前端展示组件；
- 无意义 shortcode 标记；
- 纯布局代码。

例如：

```markdown
---
title: Troubleshooting
description: ...
---

## Check whether Docker is running

Run:

```bash
docker info
```
```

处理为：

```text
Title: Troubleshooting

Section: Check whether Docker is running

Run:

docker info
```

## 7.2 不要过度清洗

特别注意：

**命令和错误信息必须保留。**

例如：

```text
Cannot connect to the Docker daemon
docker info
systemctl status docker
DOCKER_HOST
```

这些是技术支持检索中最有价值的信息。

---

# 8. Chunk 切分策略

不要简单按固定字符数硬切。

推荐：

## 第一层：按 Markdown Heading 切分

```text
# H1
## H2
### H3
```

记录 `section_path`。

## 第二层：超长 section 再切

建议：

```text
chunk tokens: 300～600
overlap: 50～100
```

代码块尽量保持完整。

## 8.1 推荐规则

```text
section < 600 tokens
→ 直接作为一个 chunk

section > 600 tokens
→ 按段落继续切

代码块
→ 不从中间切断
```

## 8.2 Chunk 内容建议增加标题

实际 Embedding 文本可以构造成：

```text
Document: Troubleshooting the Docker daemon
Section: Daemon > Unable to connect to the Docker daemon

Cannot connect to the Docker daemon...
```

这样比只 Embedding 正文更容易召回正确章节。

---

# 9. Embedding 方案

Docker 文档主要是英文，但用户可能使用中文提问，因此必须考虑跨语言检索。

推荐两种方案。

## 方案 A：本地开源模型

优先：

```text
BAAI/bge-m3
```

优点：

- 多语言；
- 本地可运行；
- 不依赖 API；
- 项目更容易复现；
- 适合中文 query → 英文 document。

## 方案 B：Embedding API

如果你已有模型 API，可以使用支持多语言语义检索的 embedding 模型。

要求：

- query 和 document 使用同一向量空间；
- 支持中英文；
- 记录 embedding model 版本。

V1 推荐先用 **bge-m3**。

---

# 10. 向量数据库

推荐：

**PostgreSQL + pgvector**

原因：

1. 你已有 PostgreSQL 基础；
2. 可以同时保存业务数据和向量；
3. 简历价值比纯内存 FAISS 更高；
4. 方便 metadata filter；
5. 后续可结合全文检索。

表结构示意：

```sql
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY,
    document_id VARCHAR(255),
    title TEXT,
    section_path JSONB,
    content TEXT,
    source_url TEXT,
    file_path TEXT,
    embedding VECTOR(1024)
);
```

向量维度根据实际 embedding 模型调整。

---

# 11. RAG 检索架构

最终建议：

```text
User Query
    │
    ▼
Query Normalization
    │
    ├──────────────┐
    ▼              ▼
Vector Search   Keyword Search
    │              │
    └──────┬───────┘
           ▼
      Candidate Merge
           │
           ▼
        Reranker
           │
           ▼
        Top-K
           │
           ▼
       LLM Answer
```

---

# 12. 检索分阶段实现

## V1：Vector Search

最简单：

```text
query
→ embedding
→ pgvector cosine search
→ top 5
```

## V2：Hybrid Search

增加关键词搜索。

原因：

Docker 技术问题包含大量：

- 错误码；
- 命令；
- 参数；
- 环境变量；
- 文件名。

例如：

```text
DOCKER_HOST
daemon.json
exit code 137
docker.sock
```

这些内容关键词检索通常非常有效。

可使用：

```text
PostgreSQL Full Text Search
+
pgvector
```

## V3：Rerank

Top 20 candidate：

```text
Vector Top10
+
Keyword Top10
```

合并去重后使用 reranker，最终得到：

```text
Top 4～6
```

推荐：

```text
BAAI/bge-reranker-v2-m3
```

---

# 13. RAG 输出要求

回答必须包含：

1. 结论；
2. 排查步骤；
3. 不确定信息；
4. 官方文档来源。

示例：

```text
从当前信息看，最可能有两个原因：

1. Docker daemon 没有启动
2. DOCKER_HOST 指向了错误的远程地址

建议依次检查：

docker info
systemctl status docker
echo $DOCKER_HOST

参考：
- Troubleshooting the Docker daemon
  https://docs.docker.com/...
```

Agent 不应该：

- 编造 Docker 参数；
- 伪造命令；
- 声称执行了实际没有执行的检查；
- 在证据不足时给出确定诊断。

---

# 14. 模型层设计

建议封装统一接口：

```python
class ChatModel:
    async def generate(self, messages, **kwargs):
        ...

    async def structured_output(self, schema, messages):
        ...
```

这样以后可以替换：

- OpenAI；
- Claude；
- Gemini；
- 国内 OpenAI-compatible API；
- 本地模型。

不要把业务逻辑全部写死在某一家 SDK 里。

---

# 15. Agent 框架

推荐：

**LangGraph**

项目重点不是“使用 LangGraph”，而是学习：

- State；
- Node；
- Conditional Edge；
- Tool Calling；
- Retry；
- Checkpoint；
- Human-in-the-loop。

---

# 16. Agent State

第一版可定义：

```python
class AgentState(TypedDict):
    messages: list
    user_query: str

    intent: str | None

    environment: dict

    retrieved_docs: list
    tool_calls: list
    tool_results: list

    missing_information: list

    diagnosis: str | None
    final_answer: str | None

    retry_count: int
```

`environment` 可以保存：

```json
{
  "os": "Ubuntu 24.04",
  "docker_type": "Docker Engine",
  "docker_version": "27.x",
  "container_name": "api-server"
}
```

---

# 17. Agent 工作流

推荐：

```text
START
  │
  ▼
understand_query
  │
  ▼
classify_intent
  │
  ├── GENERAL_QA ──────► retrieve_docs
  │
  ├── TROUBLESHOOT ───► check_information
  │
  ├── TOOL_REQUEST ───► decide_tool
  │
  └── UNKNOWN ────────► clarify_user
                           │
                           ▼
                    sufficient info?
                     │            │
                    yes           no
                     │            │
                     ▼            ▼
                 retrieve     ask_user
                     │
                     ▼
                 decide_tool
                     │
               ┌─────┴─────┐
               │           │
              yes          no
               │           │
               ▼           ▼
           execute_tool   diagnose
               │           │
               └─────┬─────┘
                     ▼
                 synthesize
                     │
                     ▼
                   END
```

---

# 18. Intent 类型

第一版控制在 5 类：

```python
GENERAL_QA
INSTALLATION
TROUBLESHOOT
CONTAINER_DIAGNOSIS
SUPPORT_TICKET
```

不要一开始做 20 个 intent。

---

# 19. Tool 设计

## 19.1 get_docker_info

作用：

获取 Docker 基本环境。

返回：

```json
{
  "version": "27.1.1",
  "server_version": "27.1.1",
  "os": "linux",
  "architecture": "x86_64"
}
```

---

## 19.2 check_daemon_status

返回：

```json
{
  "status": "running",
  "reachable": true,
  "message": "Docker daemon is reachable"
}
```

---

## 19.3 list_containers

参数：

```json
{
  "all": true
}
```

返回：

```json
[
  {
    "id": "...",
    "name": "api-server",
    "status": "exited",
    "image": "demo-api:latest"
  }
]
```

---

## 19.4 inspect_container

参数：

```json
{
  "container_name": "api-server"
}
```

返回：

```json
{
  "status": "exited",
  "exit_code": 137,
  "oom_killed": true,
  "restart_count": 3
}
```

---

## 19.5 get_container_logs

参数：

```json
{
  "container_name": "api-server",
  "tail": 100
}
```

限制最大日志长度，防止把几 MB 日志塞进 LLM。

---

## 19.6 check_disk_usage

返回：

```json
{
  "disk_total_gb": 512,
  "disk_used_percent": 94,
  "docker_root_usage_gb": 180
}
```

---

## 19.7 create_support_ticket

输入：

```json
{
  "title": "...",
  "problem": "...",
  "environment": {},
  "diagnosis": "...",
  "actions_taken": [],
  "logs": []
}
```

输出：

```json
{
  "ticket_id": "T-2026-0001",
  "status": "created"
}
```

---

# 20. Tool 两种运行模式

## Mock Mode

没有 Docker 环境也可以开发。

```text
mock/
hosts.json
containers.json
tickets.json
```

工具读取 JSON 返回模拟结果。

## Real Mode

后期再通过 Docker SDK / Docker Engine API 读取本机 Docker。

配置：

```env
TOOL_MODE=mock
```

或者：

```env
TOOL_MODE=local
```

项目演示时两种模式都支持，会很加分。

---

# 21. 工具安全设计

第一版工具原则：

**只读优先。**

允许：

- inspect；
- logs；
- list；
- status；
- info。

不允许 Agent 自动：

```text
docker rm
docker system prune
docker volume rm
docker stop
docker restart
```

如果以后加入修改型操作，需要：

```text
Agent 决策
→ 明确展示操作
→ 用户确认
→ 执行
```

---

# 22. 多轮对话设计

例子：

用户：

```text
Docker 启动不了。
```

Agent：

```text
请告诉我：
1. 操作系统
2. Docker Engine 还是 Docker Desktop
3. 具体错误信息
```

用户：

```text
Ubuntu 24.04，Docker Engine，报 Cannot connect to the Docker daemon。
```

State 更新：

```json
{
  "os": "Ubuntu 24.04",
  "docker_type": "Docker Engine",
  "error": "Cannot connect to the Docker daemon"
}
```

后续不能再次询问已经获得的信息。

---

# 23. Memory 设计

区分：

## Working Memory

当前一次故障诊断。

例如：

- OS；
- Docker Version；
- Container；
- Error；
- 已执行步骤。

## Conversation History

保留最近 N 条 message。

## Long-term Memory

V1 不做。

不要一开始实现复杂用户画像或跨会话记忆。

---

# 24. 后端 API

推荐 FastAPI。

## POST /api/chat

Request：

```json
{
  "conversation_id": "uuid",
  "message": "api-server 为什么一直退出？"
}
```

Response：

```json
{
  "answer": "...",
  "sources": [],
  "tool_calls": [],
  "conversation_id": "..."
}
```

---

## POST /api/knowledge/rebuild

重新构建知识库。

---

## GET /api/knowledge/stats

返回：

```json
{
  "documents": 120,
  "chunks": 830,
  "embedding_model": "bge-m3"
}
```

---

## POST /api/eval/run

执行评测。

---

## GET /api/conversations/{id}

调试时查看 conversation state。

---

# 25. 前端设计

第一阶段不用投入太多时间。

推荐：

```text
Vue
```

因为你已有 Vue 基础。

页面只做：

```text
┌──────────────────────────────────┐
│ Docker Support Agent             │
├──────────────────────────────────┤
│                                  │
│ User                             │
│ ...                              │
│                                  │
│ Agent                            │
│ ...                              │
│                                  │
│ Sources                          │
│ • Troubleshooting Docker daemon  │
│                                  │
│ Tool Calls                       │
│ • check_daemon_status            │
│                                  │
├──────────────────────────────────┤
│ input                     Send   │
└──────────────────────────────────┘
```

开发项目最值得展示的是：

- Agent Decision；
- Retrieved Documents；
- Tool Calls；
- Sources。

可以额外加一个 Debug Panel。

---

# 26. PostgreSQL 表设计

最少：

```text
document_chunks
conversations
messages
tickets
eval_runs
```

## conversations

```sql
id
created_at
updated_at
state
```

## messages

```sql
id
conversation_id
role
content
created_at
```

## tickets

```sql
id
title
problem
environment
diagnosis
status
created_at
```

---

# 27. Redis 是否需要

V1：

**不需要。**

等系统完整运行后再加。

V2 Redis 可用于：

- session cache；
- short-term state；
- rate limit；
- retrieval cache。

不要为了简历技术栈强行加 Redis。

---

# 28. 项目目录

推荐：

```text
docker-support-agent/
│
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── routers/
│   │   └── dependencies/
│   │
│   └── web/
│
├── src/
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   └── prompts/
│   │
│   ├── rag/
│   │   ├── loader.py
│   │   ├── cleaner.py
│   │   ├── splitter.py
│   │   ├── embeddings.py
│   │   ├── retriever.py
│   │   └── reranker.py
│   │
│   ├── tools/
│   │   ├── docker_info.py
│   │   ├── daemon.py
│   │   ├── containers.py
│   │   ├── logs.py
│   │   ├── disk.py
│   │   └── ticket.py
│   │
│   ├── llm/
│   │   ├── client.py
│   │   └── schemas.py
│   │
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── repositories/
│   │
│   └── eval/
│       ├── retrieval.py
│       ├── tools.py
│       └── agent.py
│
├── scripts/
│   ├── download_docs.py
│   ├── select_docs.py
│   ├── build_documents.py
│   ├── build_index.py
│   └── run_eval.py
│
├── data/
│   ├── raw/
│   ├── selected/
│   ├── processed/
│   ├── mock/
│   └── eval/
│
├── tests/
│
├── docker/
│
├── .env.example
├── pyproject.toml
├── compose.yaml
└── README.md
```

---

# 29. Python 环境

推荐：

```text
Python 3.12
uv
```

初始化：

```bash
uv init
```

核心依赖：

```text
fastapi
uvicorn
pydantic
sqlalchemy
psycopg
pgvector
langgraph
httpx
markdown-it-py
beautifulsoup4
sentence-transformers
```

后期：

```text
rank-bm25
docker
redis
```

依赖不要一次装完。

---

# 30. 配置管理

`.env.example`

```env
APP_ENV=development

DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent

MODEL_PROVIDER=
MODEL_NAME=
MODEL_API_KEY=
MODEL_BASE_URL=

EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3

TOOL_MODE=mock

RETRIEVAL_TOP_K=10
RERANK_TOP_K=5
```

API Key 永远不要提交 Git。

---

# 31. Prompt 设计原则

System Prompt 不要写成几十页说明书。

包含：

1. 身份；
2. 能力；
3. 行为边界；
4. 工具原则；
5. 文档依据原则；
6. 安全原则。

例如：

```text
你是 Docker 技术支持 Agent。

你的任务是帮助用户定位 Docker Engine、Container、Network、
Storage 和 Compose 相关问题。

原则：

1. 技术事实优先依据检索到的 Docker 官方文档。
2. 信息不足时主动询问，不要猜测。
3. 当工具可以提供真实环境信息时，优先使用工具。
4. 不得声称执行了未实际执行的命令。
5. 高风险操作只能建议，不得自动执行。
6. 最终答案给出排查步骤与来源。
```

---

# 32. Structured Output

Agent 的关键决策尽量使用结构化输出。

Intent：

```python
class IntentResult(BaseModel):
    intent: Literal[
        "general_qa",
        "installation",
        "troubleshoot",
        "container_diagnosis",
        "support_ticket",
    ]

    confidence: float
    missing_information: list[str]
```

Diagnosis：

```python
class DiagnosisResult(BaseModel):
    summary: str
    possible_causes: list[str]
    recommended_actions: list[str]
    need_more_info: bool
```

不要依赖正则解析 LLM 自由文本。

---

# 33. Evaluation 数据集

这是整个项目很重要的一部分。

## 33.1 Retrieval Eval

格式：

```json
{
  "query": "Docker client says Cannot connect to the Docker daemon",
  "relevant_document": "engine/daemon/troubleshoot",
  "relevant_section": "Unable to connect to the Docker daemon"
}
```

建议第一版：

```text
50 条
```

指标：

```text
Recall@1
Recall@3
Recall@5
MRR
```

---

# 34. Tool Eval

例如：

```json
{
  "query": "帮我看看 api-server 为什么退出",
  "expected_tools": [
    "inspect_container",
    "get_container_logs"
  ]
}
```

指标：

```text
Tool Selection Accuracy
Tool Parameter Accuracy
```

---

# 35. Agent Eval

场景：

### Case 1

用户：

```text
Docker daemon 连不上。
```

预期行为：

```text
主动获取或询问环境
检索 daemon troubleshooting
检查 daemon
给出排查步骤
```

### Case 2

用户：

```text
api-server exit code 137。
```

预期：

```text
inspect
logs
检索 OOM / resource constraint 文档
解释可能存在内存问题
```

建议：

```text
30～50 个端到端 case
```

---

# 36. Hallucination 测试

故意提出不存在的问题：

```text
Docker error code DKR-99881 是什么？
```

预期：

Agent 不能编答案。

应该：

```text
当前官方文档和工具结果中没有找到该错误码。
请提供完整错误日志或上下文。
```

---

# 37. 可观测性

每次请求至少记录：

```text
request_id
conversation_id
model
latency
retrieved_chunk_ids
retrieval_scores
rerank_scores
tool_calls
tool_latency
token_usage
final_status
```

前期存 JSON Log 即可。

后期再考虑：

- LangSmith；
- OpenTelemetry；
- Prometheus。

不要第一周就接复杂监控系统。

---

# 38. 错误处理

必须考虑：

## LLM API Failure

```text
retry 2 次
→ fallback message
```

## Retrieval Failure

没有结果：

```text
明确告诉用户没有找到可靠文档依据
```

## Tool Failure

例如 Docker daemon 本身无法连接：

Tool 返回：

```json
{
  "success": false,
  "error_type": "daemon_unreachable",
  "message": "..."
}
```

Agent 根据 error 继续诊断。

## Invalid Arguments

工具使用 Pydantic 校验参数。

---

# 39. 测试策略

## Unit Test

重点：

```text
Markdown Cleaner
Splitter
Retriever
Tool
Schema
```

## Integration Test

```text
Query
→ Retrieval
→ LLM
```

## Agent Test

```text
User
→ Graph
→ Tool
→ RAG
→ Answer
```

不要追求 100% coverage。

优先测试核心流程。

---

# 40. 开发里程碑

---

## Milestone 0：项目初始化

目标：

```text
项目可启动
PostgreSQL 可连接
FastAPI /health 正常
```

任务：

- Git 初始化；
- uv；
- FastAPI；
- Docker Compose；
- PostgreSQL；
- `.env`；
- README。

验收：

```bash
curl localhost:8000/health
```

返回：

```json
{"status":"ok"}
```

---

## Milestone 1：Docker Docs 数据管道

目标：

```text
Docker Docs
→ Markdown
→ Clean Document
→ Chunk JSONL
```

任务：

- 下载仓库；
- 文档筛选；
- Markdown parser；
- front matter 处理；
- heading splitter；
- metadata；
- JSONL。

验收：

```text
能够随机抽 20 个 chunk
人工检查：
标题正确
章节正确
代码没损坏
来源 URL 正确
```

---

## Milestone 2：基础 RAG

目标：

```text
Question
→ Vector Search
→ Docs
→ Answer
```

任务：

- bge-m3；
- pgvector；
- index；
- retrieval API；
- RAG prompt；
- source citation。

验收问题：

```text
Cannot connect to Docker daemon
Docker volume vs bind mount
How to inspect container logs
Docker container OOM
```

答案必须能找到相关官方文档。

---

## Milestone 3：RAG 优化

目标：

```text
Hybrid Retrieval + Rerank
```

任务：

- keyword search；
- fusion；
- reranker；
- retrieval eval。

输出实验：

```text
Vector only
vs
Vector + Keyword
vs
Hybrid + Rerank
```

比较：

```text
Recall@5
MRR
```

这会成为简历里非常好的技术点。

---

## Milestone 4：Tool Calling

目标：

Agent 可以真实获取 Docker 环境。

先做：

```text
get_docker_info
check_daemon_status
list_containers
inspect_container
get_container_logs
```

先 Mock，再 Real。

验收：

用户：

```text
api-server 怎么退出了？
```

Agent 能正确选择工具。

---

## Milestone 5：LangGraph Agent

目标：

从固定 RAG 流程升级为 Agent。

节点：

```text
classify
clarify
retrieve
decide_tool
execute_tool
diagnose
answer
```

验收：

三类场景：

```text
纯问答
信息不足
工具诊断
```

全部能正确路由。

---

## Milestone 6：Conversation State

目标：

Agent 支持多轮故障排查。

验收：

第一轮：

```text
Docker 启动不了
```

第二轮：

```text
Ubuntu 24.04
```

第三轮：

```text
Cannot connect...
```

Agent 正确累积状态，不重复询问。

---

## Milestone 7：Evaluation

目标：

形成完整评测报告。

至少：

```text
50 retrieval
30 tool
30 agent
```

最终输出：

```text
reports/eval_report.md
```

---

## Milestone 8：Web Demo

目标：

一个可展示页面。

显示：

```text
Chat
Sources
Tool Calls
Agent Steps
```

不是追求精美，而是让面试官看懂系统运行过程。

---

# 41. 推荐开发顺序

不要同时开发所有模块。

严格按：

```text
数据
 ↓
RAG
 ↓
RAG Eval
 ↓
Tool
 ↓
Agent Workflow
 ↓
Memory
 ↓
Agent Eval
 ↓
Frontend
```

这是本项目最重要的实施原则之一。

---

# 42. 第一周计划

## Day 1

- 建仓库；
- uv；
- FastAPI；
- PostgreSQL；
- compose。

## Day 2

- clone Docker Docs；
- 查看文档结构；
- 确定文档白名单。

## Day 3

- Markdown loader；
- metadata。

## Day 4

- cleaner；
- heading splitter。

## Day 5

- chunks.jsonl；
- 人工检查。

## Day 6

- embedding；
- pgvector。

## Day 7

实现：

```text
query → top5 chunks
```

第一周结束时：

**不要做 Agent。**

只需要让检索稳定工作。

---

# 43. 第二周计划

目标：

完整 RAG。

实现：

```text
Query
→ Retrieval
→ Context
→ LLM
→ Answer + Source
```

并制作第一批 20～30 条 retrieval 测试集。

---

# 44. 第三周计划

目标：

Tool Calling。

做：

```text
Mock Docker Tool
→ Real Docker Tool
```

测试：

```text
daemon down
container exit
OOM
disk full
```

---

# 45. 第四周计划

目标：

LangGraph Agent。

重点：

```text
routing
clarification
tool call
retry
state
```

---

# 46. 第五～六周

做：

- Evaluation；
- Web；
- README；
- Architecture diagram；
- Demo video；
- 简历描述。

---

# 47. README 最终结构

项目完成后 README 推荐：

```text
# Docker Support Agent

## Overview

## Demo

## Features

## Architecture

## Agent Workflow

## RAG Pipeline

## Tool System

## Evaluation

## Quick Start

## Dataset

## Project Structure

## Limitations

## Roadmap
```

一定要有：

**Architecture 图 + Agent Workflow 图 + Evaluation 数据。**

---

# 48. 项目完成标准

只有满足以下条件，才算“完成”。

## RAG

- [ ] 官方 Docker Docs 数据；
- [ ] Metadata；
- [ ] Vector retrieval；
- [ ] Hybrid retrieval；
- [ ] Rerank；
- [ ] Source citation。

## Agent

- [ ] Intent；
- [ ] Clarification；
- [ ] Tool selection；
- [ ] Tool execution；
- [ ] State；
- [ ] Retry；
- [ ] Final response。

## Tool

- [ ] Docker info；
- [ ] daemon；
- [ ] containers；
- [ ] inspect；
- [ ] logs。

## Evaluation

- [ ] Retrieval；
- [ ] Tool；
- [ ] E2E Agent。

## Engineering

- [ ] FastAPI；
- [ ] PostgreSQL；
- [ ] Docker Compose；
- [ ] Unit Test；
- [ ] README。

---

# 49. 项目做到什么程度可以写简历

## 完成 Milestone 2

只能写：

```text
Docker 官方文档 RAG 问答系统
```

不要叫完整 Agent。

## 完成 Milestone 5

可以写：

```text
Docker Support Agent
```

因为已经真正具备：

```text
决策
RAG
Tool Calling
Workflow
```

## 完成 Milestone 7

这时项目才真正有较强简历竞争力。

---

# 50. 最终简历描述模板

以下内容必须等对应功能真实实现后再写。

### Docker Support Agent｜Docker 智能技术支持 Agent

**Python · FastAPI · LangGraph · PostgreSQL · pgvector · RAG**

- 基于 Docker 官方开源文档构建技术知识库，设计 Markdown 清洗、层级切分、Embedding、混合检索与 Rerank 流程，并保留文档级引用与溯源信息。
- 基于 LangGraph 构建有状态 Agent 工作流，实现意图判断、信息追问、知识检索、工具调用、故障诊断和结果生成等节点的条件路由。
- 封装 Docker 环境检测、容器 Inspect、日志获取等工具，实现 LLM 对本地 Docker 运行状态的结构化调用与诊断。
- 构建 Retrieval / Tool / Agent 三层评测集，通过 Recall@K、工具选择准确率和任务成功率对系统进行自动化评估。

实际指标出来后加入：

```text
Recall@5 xx%
Tool Accuracy xx%
Task Success Rate xx%
```

禁止提前虚构数据。

---

# 51. 项目核心面试问题

项目做完以后必须能回答：

### RAG

- 为什么选 Markdown heading split？
- Chunk 为什么设置这个大小？
- 为什么 Docker 问题适合 Hybrid Search？
- 为什么需要 Reranker？
- 中文 query 怎么检索英文文档？
- 如何防止检索不到答案时 hallucination？

### Agent

- 为什么需要 LangGraph？
- Agent 和普通 Chain 有什么区别？
- State 中保存什么？
- 什么情况下追问用户？
- 工具调用失败怎么办？
- 如何防止无限循环？

### Tool

- Tool Schema 怎么设计？
- 为什么要 Structured Output？
- 日志太长怎么办？
- 为什么工具先做只读？

### Evaluation

- 怎么判断 retrieval 好不好？
- Recall@K 是什么？
- 怎么评 Tool Call？
- 如何测试 Agent 而不是只看 Demo？

这些问题才是这个项目真正的学习价值。

---

# 52. 后续扩展方向

完成主项目后再考虑：

## V2

```text
GitHub Issue Retrieval
```

官方文档 + 社区真实问题。

## V3

```text
Docker Compose Diagnosis
```

解析 compose.yaml。

## V4

```text
Log Analysis
```

大日志切分 + 异常摘要。

## V5

```text
Human-in-the-loop
```

高风险操作用户确认。

## V6

```text
Realtime Voice
```

连接语音实时模型，变成语音技术客服 Agent。

---

# 53. 当前最重要的原则

在整个开发过程中，始终遵守：

> **先把最简单的流程做正确，再增加 Agent 复杂度。**

不要第一天就写：

```text
multi-agent
planner
reflection
memory
MCP
```

这些名词。

项目真正重要的是：

```text
数据质量
检索质量
工具可靠性
流程控制
评测
```

一个稳定的：

```text
RAG + 5 个 Tool + LangGraph Workflow + Evaluation
```

远比一个堆满框架但无法测试的“Multi-Agent Platform”更有价值。

---

# 54. 推荐的第一次实际开发任务

从这里开始：

```text
Milestone 1：Docker Docs 数据管道
```

第一步只实现：

```text
docker/docs
        ↓
筛选 markdown
        ↓
解析 front matter
        ↓
提取 heading
        ↓
生成 documents.jsonl
        ↓
生成 chunks.jsonl
```

**暂时不要调用 LLM。**

当你能稳定输出高质量 `chunks.jsonl` 后，再进入 Embedding 和 RAG。

---

# 55. 官方数据来源

Docker Docs：

```text
https://github.com/docker/docs
```

Docker Docs Website：

```text
https://docs.docker.com/
```

Daemon troubleshooting：

```text
https://docs.docker.com/engine/daemon/troubleshoot/
```

Docker Docs 源代码仓库 README 明确说明该仓库是 Docker Documentation 网站的源仓库，并采用 Apache License 2.0。

项目公开时建议：

- README 中注明数据来源；
- 保留 Docker 文档来源 URL；
- 保留许可证说明；
- 不宣称 Docker 官方认可或维护本项目；
- 如长期保存大规模文档快照，重新确认对应版本许可证要求。

---

# 56. 项目最终成功标准

如果最终面试官看到这个项目，理想的交流不是：

> “你用过 LangChain 吗？”

而是：

> “你这个检索为什么这么设计？”
>
> “工具执行失败的时候 Agent 怎么恢复？”
>
> “中文问题检索英文 Docker 文档效果怎么样？”
>
> “怎么评估 Agent 是否真的完成任务？”
>
> “如果用户给了错误日志，你如何防止上下文过长？”

当面试进入这些问题时，这个项目就真正发挥价值了。
