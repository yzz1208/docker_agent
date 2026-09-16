# Docker Support Agent

基于 Docker 官方文档逐步实现的技术支持 Agent。项目按 **数据管道 → RAG → Tool Calling → Agent Workflow → Evaluation** 的顺序推进，当前分支首先完成 Milestone 0：项目初始化。

完整设计见：[`doc/Docker_Support_Agent_开发文档.md`](doc/Docker_Support_Agent_开发文档.md)。

## 当前进度

- [x] Python 3.12 + uv 项目结构
- [x] FastAPI 基础服务
- [x] `.env` 配置管理
- [x] PostgreSQL Docker Compose
- [x] 数据库连通性检查
- [x] `/health` 健康检查
- [x] `/health/db` 数据库健康检查
- [x] pytest 基础测试
- [ ] Docker Docs 数据管道
- [ ] RAG
- [ ] Tool Calling
- [ ] LangGraph Agent
- [ ] Evaluation

## 环境要求

推荐环境：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 或 Docker Engine + Docker Compose
- Git

## 本地启动

### 1. 克隆仓库

```bash
git clone https://github.com/yzz1208/docker_agent.git
cd docker_agent
```

如果要测试当前开发分支：

```bash
git checkout feat/milestone-0-bootstrap
```

### 2. 安装依赖

```bash
uv sync --all-groups
```

`uv` 会自动创建 `.venv`，不需要手动 `python -m venv`。

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

### 4. 启动 PostgreSQL

```bash
docker compose up -d postgres
```

查看状态：

```bash
docker compose ps
```

第一次启动等待几秒，直到 PostgreSQL health 状态为 `healthy`。

### 5. 启动 FastAPI

```bash
uv run uvicorn docker_agent.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器访问：

- API 文档：http://127.0.0.1:8000/docs
- 基础健康检查：http://127.0.0.1:8000/health
- 数据库健康检查：http://127.0.0.1:8000/health/db

预期 `/health` 返回：

```json
{
  "status": "ok",
  "app": "Docker Support Agent",
  "env": "development"
}
```

预期 `/health/db` 返回：

```json
{
  "status": "ok",
  "database": "reachable"
}
```

### 6. 运行测试

```bash
uv run pytest -v
```

### 7. 代码质量检查

```bash
uv run ruff check .
```

## 项目结构

```text
docker_agent/
├── doc/
│   └── Docker_Support_Agent_开发文档.md
├── src/
│   └── docker_agent/
│       ├── __init__.py
│       ├── config.py      # 环境变量与应用配置
│       ├── db.py          # PostgreSQL 连接与连通性检查
│       └── main.py        # FastAPI 应用入口
├── tests/
│   └── test_health.py     # 基础 API 测试
├── .env.example           # 可提交的配置模板，不包含密钥
├── .gitignore
├── compose.yaml           # 本地 PostgreSQL
├── pyproject.toml         # Python 依赖、构建与工具配置
└── README.md
```

## Milestone 0 为什么这样设计

这一阶段故意不加入 LangGraph、Embedding、pgvector 和模型 SDK。先建立一个可以重复启动、测试、配置和连接数据库的最小后端骨架，后续每一个模块都在这个骨架上增加，避免项目从第一天就变成难以调试的“大杂烩”。

`/health` 只检查 Web 服务本身，因此即使 PostgreSQL 没启动，它仍应返回 200；`/health/db` 单独检查数据库依赖。这样以后部署时可以区分“应用进程活着”和“依赖服务可用”。

## 下一步

Milestone 1 将实现 Docker Docs 数据管道：

```text
Docker Docs
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

这一阶段仍然不会调用 LLM，先保证知识库原始数据质量。
