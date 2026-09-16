# Docker Support Agent

基于 Docker 官方文档逐步实现的技术支持 Agent。项目按 **数据管道 → RAG → Tool Calling → Agent Workflow → Evaluation** 的顺序推进。

完整设计见：[`doc/Docker_Support_Agent_开发文档.md`](doc/Docker_Support_Agent_开发文档.md)。

## 当前进度

- [x] Python 3.12 + uv 项目结构
- [x] FastAPI 基础服务
- [x] `.env` 配置管理
- [x] PostgreSQL + pgvector Docker Compose
- [x] 数据库连通性检查
- [x] `/health` 健康检查
- [x] `/health/db` 数据库健康检查
- [x] pytest 基础测试
- [ ] Docker Docs 数据管道
- [ ] RAG
- [ ] Tool Calling
- [ ] LangGraph Agent
- [ ] Evaluation

## 当前技术选择

本项目从一开始直接使用 PostgreSQL，不再使用 SQLite。Compose 使用 `pgvector/pgvector:pg16`，这样后续进入 Embedding / RAG 阶段时无需重新迁移数据库镜像。

数据库初始化时会执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

当前虽然还没有创建向量表，但 pgvector 环境会提前准备好。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop / Docker Engine
- Git

Milestone 0 不需要配置大模型 API Key。

## 本地启动

### 1. 克隆仓库并切换开发分支

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

### 2. 安装 Python 依赖

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

默认数据库连接：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent
```

### 4. 启动 PostgreSQL + pgvector

```bash
docker compose up -d postgres
```

查看状态：

```bash
docker compose ps
```

等待 `docker-agent-postgres` 变成 `healthy`。

也可以查看启动日志：

```bash
docker compose logs postgres
```

### 5. 验证 PostgreSQL

```bash
docker compose exec postgres psql -U postgres -d docker_agent -c "SELECT version();"
```

验证 pgvector 扩展：

```bash
docker compose exec postgres psql -U postgres -d docker_agent -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

如果能返回版本号，说明 pgvector 已启用。

> 如果你曾经用同一个 Compose volume 启动过数据库，初始化脚本不会再次自动执行。此时可以手动运行：
>
> ```bash
> docker compose exec postgres psql -U postgres -d docker_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"
> ```

### 6. 启动 FastAPI

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

### 7. 自动化测试

```bash
uv run pytest -v
```

### 8. 代码质量检查

```bash
uv run ruff check .
```

### 9. 停止数据库

只停止容器、保留数据库数据：

```bash
docker compose down
```

如果明确想连数据库数据卷一起删除：

```bash
docker compose down -v
```

`-v` 会删除 PostgreSQL 数据，请不要随便使用。

## 项目结构

```text
docker_agent/
├── doc/
│   └── Docker_Support_Agent_开发文档.md
├── docker/
│   └── postgres/
│       └── init/
│           └── 001-enable-vector.sql
├── src/
│   └── docker_agent/
│       ├── __init__.py
│       ├── config.py      # 环境变量与应用配置
│       ├── db.py          # SQLAlchemy 数据库连接与健康检查
│       └── main.py        # FastAPI 应用入口
├── tests/
│   └── test_health.py
├── .env.example
├── .gitignore
├── compose.yaml           # PostgreSQL 16 + pgvector
├── pyproject.toml
└── README.md
```

## Milestone 0 的设计思路

这一阶段只建立最小、可靠的后端骨架：

```text
FastAPI
   ↓
SQLAlchemy
   ↓
psycopg
   ↓
PostgreSQL + pgvector
```

`/health` 只检查 Web 服务本身；`/health/db` 单独检查 PostgreSQL。这样以后可以区分“应用进程正常”与“数据库依赖正常”。

数据库连接统一从 `DATABASE_URL` 读取，因此业务代码不需要知道 PostgreSQL 的用户名、端口等细节。

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

这一阶段仍然不会调用 LLM，先把知识库原始数据质量做好。
