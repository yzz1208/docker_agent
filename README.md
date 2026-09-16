# Docker Support Agent

基于 Docker 官方文档逐步实现的技术支持 Agent。项目按 **数据管道 → RAG → Tool Calling → Agent Workflow → Evaluation** 的顺序推进。

完整设计见：[`doc/Docker_Support_Agent_开发文档.md`](doc/Docker_Support_Agent_开发文档.md)。

## 当前进度

- [x] Python 3.12 + uv 项目结构
- [x] FastAPI 基础服务
- [x] `.env` 配置管理
- [x] SQLite 零依赖本地数据库
- [x] 可选 PostgreSQL Docker Compose 配置
- [x] `/health` 健康检查
- [x] `/health/db` 数据库健康检查
- [x] pytest 基础测试
- [ ] Docker Docs 数据管道
- [ ] RAG
- [ ] Tool Calling
- [ ] LangGraph Agent
- [ ] Evaluation

## 为什么现在不要求安装 Docker

虽然最终项目叫 Docker Support Agent，但前几个里程碑主要开发：

```text
FastAPI → Docker Docs 数据管道 → RAG → Evaluation
```

这些工作并不需要本机 Docker Engine。

因此当前开发环境默认使用 Python 自带的 **SQLite**：

```env
DATABASE_URL=sqlite:///./docker_agent.db
```

这样只安装 Python、uv、Git 就能运行项目。

等后续进入：

- pgvector 向量数据库；
- 真实 Docker Tool Calling；
- inspect / logs / daemon status；

再安装 Docker Desktop，并把数据库切换到 PostgreSQL + pgvector。

## 当前环境要求

必须：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Git

当前阶段**不需要 Docker**，也不需要 PostgreSQL。

## 本地启动

### 1. 克隆仓库

```bash
git clone https://github.com/yzz1208/docker_agent.git
cd docker_agent
git checkout feat/milestone-0-bootstrap
```

如果已经 clone：

```bash
git fetch
git checkout feat/milestone-0-bootstrap
git pull
```

### 2. 安装依赖

```bash
uv sync --all-groups
```

`uv` 会自动创建 `.venv`，不需要手动创建虚拟环境。

### 3. 创建本地配置

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

Linux / macOS：

```bash
cp .env.example .env
```

Milestone 0 不需要配置大模型 API Key。

### 4. 启动 FastAPI

```bash
uv run uvicorn docker_agent.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000/docs
```

测试：

```text
GET /health
GET /health/db
```

预期 `/health`：

```json
{
  "status": "ok",
  "app": "Docker Support Agent",
  "env": "development"
}
```

预期 `/health/db`：

```json
{
  "status": "ok",
  "database": "reachable"
}
```

第一次调用数据库时，项目根目录可能出现：

```text
docker_agent.db
```

这是本地 SQLite 数据库文件，已经加入 `.gitignore`，不会被提交到 GitHub。

### 5. 自动化测试

```bash
uv run pytest -v
```

### 6. 代码质量检查

```bash
uv run ruff check .
```

## 可选：以后使用 PostgreSQL

仓库仍保留 `compose.yaml`，安装 Docker Desktop 后可运行：

```bash
docker compose up -d postgres
```

然后把 `.env` 中：

```env
DATABASE_URL=sqlite:///./docker_agent.db
```

改为：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent
```

应用代码不需要修改，因为数据库连接统一由 SQLAlchemy 和 `DATABASE_URL` 管理。

## 项目结构

```text
docker_agent/
├── doc/
│   └── Docker_Support_Agent_开发文档.md
├── src/
│   └── docker_agent/
│       ├── __init__.py
│       ├── config.py      # 环境变量与应用配置
│       ├── db.py          # 数据库连接与健康检查
│       └── main.py        # FastAPI 应用入口
├── tests/
│   └── test_health.py
├── .env.example
├── .gitignore
├── compose.yaml           # 后续可选 PostgreSQL
├── pyproject.toml
└── README.md
```

## Milestone 0 的设计思路

当前阶段故意不加入 LangGraph、Embedding、pgvector 和模型 SDK。

先建立一个能够：

```text
启动
配置
访问数据库
运行测试
```

的最小后端骨架。

同时让本地开发不依赖 Docker，降低环境准备成本。

`/health` 只检查 Web 服务，`/health/db` 单独检查数据库依赖，因此以后可以明确区分应用进程问题和数据库问题。

## 下一步

Milestone 1 将实现 Docker Docs 数据管道：

```text
Docker Docs Git Repository
    ↓
筛选 Markdown
    ↓
解析 Front Matter / Heading
    ↓
清洗内容
    ↓
生成 documents.jsonl
    ↓
生成 chunks.jsonl
```

这一阶段同样不要求安装 Docker，也不会调用 LLM。
