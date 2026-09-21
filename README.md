# Docker Support Agent

基于 Docker 官方文档构建的技术支持 Agent 项目，按照“数据 → 检索 → 工具 → Agent 工作流 → 评测”的顺序逐步实现。

## 当前进度

- Milestone 0：FastAPI + PostgreSQL/pgvector 基础环境 ✅
- Milestone 1：Docker Docs 数据管线、Markdown 清洗、Chunk 与质量审计 ✅
- Milestone 2：BGE-M3 Dense Retrieval + pgvector ✅
- Milestone 3：Hybrid Retrieval + RRF + BGE Reranker + Retrieval Eval ✅
- Milestone 4：Grounded Answer + Docs Citation + Runtime Tools + Router ✅
- Milestone 5：Dynamic Workflow + Failure/Timeout/Permission Recovery + Agent Eval ✅
- Upgrade Phase 1：Unified ToolResult + Evidence + AgentState + Shadow Migration ✅
- Upgrade Phase 2A：Coarse-Grained LangGraph Migration ✅
- Upgrade Phase 2B：Runtime Loop LangGraph Migration ✅
- Upgrade Phase 3A：Role Separation / Multi-Agent Architecture ✅
- Upgrade Phase 3B：Persistence + Agent Configuration + Effective Config API ✅
- Upgrade Phase 4：Vue 3 Web Product Shell ✅（UI/交互细节后续优化）
- Upgrade Phase 5：Observability + Evaluation Ops ✅
- Upgrade Phase 6：Production / Deployment Hardening ✅（Step 1–7 已实现，待最终 production gate）

## 本地环境

推荐：

- Python 3.12
- uv
- Docker Desktop
- PostgreSQL 16 + pgvector（通过 Compose）

安装依赖：

```powershell
uv sync --all-groups
```

启动 PostgreSQL：

```powershell
docker compose up -d postgres
```

首次使用空数据库时，先应用产品数据库迁移：

```powershell
uv run alembic upgrade head
```

如果是 Phase 5 已经通过 `create_all()` 建好当前完整产品表的本地数据库，只在首次接入
Alembic 时执行一次：

```powershell
uv run alembic stamp head
```

之后所有长期数据库都使用 Alembic 管理 schema，不再由 FastAPI 启动时自动建表。

## Milestone 1：构建 Docker Docs 数据

```powershell
uv run python scripts/download_docs.py
uv run python scripts/select_docs.py
uv run python scripts/build_docs.py
uv run python scripts/audit_chunks.py
```

处理后的数据：

```text
data/processed/documents.jsonl
data/processed/chunks.jsonl
```

## Milestone 2：Dense Retrieval

初始化 pgvector 表：

```powershell
uv run python scripts/init_vector_store.py
```

第一次建议先索引少量 Chunk：

```powershell
uv run python scripts/index_chunks.py --reset --limit 20 --batch-size 4
```

确认流程正常后再索引全部 Chunk：

```powershell
uv run python scripts/index_chunks.py --reset --batch-size 4
```

搜索：

```powershell
uv run python scripts/search_docs.py "Docker daemon 连不上怎么办" --top-k 5
```

### Retrieval Evaluation

当前提供一个小型人工标注 baseline，用来验证评测框架；后续会继续扩展到 30～50 条以上：

```text
data/eval/retrieval_baseline.jsonl
```

运行：

```powershell
uv run python scripts/eval_retrieval.py
```

当前输出指标：

- Hit@1 / Hit@3 / Hit@5：Top-K 内是否至少命中一个相关文档
- Recall@1 / Recall@3 / Recall@5：相关文档被召回的比例
- MRR：第一个相关结果排名的倒数均值

当前 baseline 使用 `file_path` 作为稳定标签，而不是 `chunk_id`。这样以后调整 Chunk 大小或重新生成 Chunk 时，不会因为 Chunk ID 变化导致整套评测标签失效。

## 测试

```powershell
uv run ruff check .
uv run pytest -v
```

## 配置

复制：

```powershell
Copy-Item .env.example .env
```

常用配置示例：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/docker_agent
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cuda
EMBEDDING_CACHE_DIR=F:/models/huggingface
EMBEDDING_BATCH_SIZE=4
RETRIEVAL_TOP_K=10
```

如果没有 CUDA，可以不设置 `EMBEDDING_DEVICE` 或设置为 `cpu`。


## Web 前端

Phase 4 前端位于：

```text
web/
```

启动后端前确认 migration 已到 head：

```powershell
uv run alembic current
uv run alembic upgrade head
```

再启动后端：

```powershell
uv run uvicorn docker_agent.main:app --reload
```

生产化 readiness：

```text
GET /health/ready
```

启动前端：

```powershell
cd web
npm install
npm run dev
```

开发环境默认通过 Vite 将 `/chat`、`/conversations`、`/agent-configurations`
和 `/health` 代理到 `http://127.0.0.1:8000`。

前端门禁：

```powershell
npm run typecheck
npm test
npm run build
```

后端与 PostgreSQL 启动后可运行只读集成检查：

```powershell
npm run smoke
```


## Production Compose

完整生产化本地栈：

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

默认只对宿主机暴露 Web：

~~~text
http://127.0.0.1:8080
~~~

容器启动顺序：

~~~text
PostgreSQL
  ↓
Alembic migration
  ↓
RAG schema bootstrap
  ↓
FastAPI readiness
  ↓
Nginx / Vue
~~~

通过 Nginx 跑完整只读 smoke：

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
npm run smoke
Remove-Item Env:BACKEND_URL
~~~

生产 Compose 默认不挂载 Docker socket，并默认使用 `TOOL_MODE=mock`。真实宿主机 Docker
控制需要后续显式配置高权限部署模式。


Production Compose 只会幂等创建 `document_chunks` / pgvector schema，不会自动清空或重新
embedding 文档。全新生产数据库需要另行执行显式知识索引流程后，Docs RAG 才具备完整知识数据。


## Environment Profiles

应用配置现在按 `APP_ENV` 分层：

~~~text
development -> .env
test        -> .env.test
production  -> .env.production
~~~

模板：

~~~text
.env.example
.env.test.example
.env.production.example
~~~

Production 首次准备：

~~~powershell
Copy-Item .env.production.example .env.production
~~~

然后修改数据库密码、`DATABASE_URL` 和模型配置。真实 `.env.production` 不会提交 Git。

Production 会拒绝默认 PostgreSQL 密码、SQLite 数据库和未替换的数据库 placeholder。
FastAPI serving 启动时还会校验 `MODEL_NAME` / `MODEL_BASE_URL`。

`TOOL_MODE=mock` 现在是真正的无 Docker subprocess 模式；`TOOL_MODE=local`
才调用只读 Docker CLI。默认 production Compose 强制使用 mock 模式。


## CI

GitHub Actions 普通 CI：

~~~text
Backend quality
├─ uv sync
├─ Ruff
├─ migration/runtime contract
└─ pytest

Frontend quality
├─ typecheck
├─ unit tests
└─ production build

Production configuration
└─ docker compose config
~~~

普通 PR/Push CI 不调用真实模型，也不需要生产 secrets。Live-model regression gate 会放在独立
的显式工作流中。

Linux CI/生产容器使用 CPU PyTorch；Windows 本地开发继续使用 cu130。


## Manual Evaluation Regression Gate

普通 CI 不消耗模型额度。需要做 release 质量检查时，在 GitHub Actions 手动运行：

~~~text
Evaluation Regression Gate
~~~

需要配置：

~~~text
Variable:
EVALUATION_MODEL_NAME

Secrets:
EVALUATION_DATABASE_URL
EVALUATION_MODEL_BASE_URL
EVALUATION_MODEL_API_KEY
~~~

工作流会运行并持久化 candidate evaluation，再与输入的 `baseline_run_id` 比较。Regression 或
case set incomplete 会让工作流失败。

Evaluation DB 必须已经迁移到 Alembic head；评测脚本不会再通过 `create_all()` 修改长期数据库
schema。


## Production Runbook & Monitoring

完整生产运维流程见：

~~~text
doc/Production_Runbook.md
~~~

可选 Prometheus monitoring profile：

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring up -d
~~~

默认 Prometheus：

~~~text
http://127.0.0.1:9090
~~~

Prometheus 通过 Compose 内部网络抓取：

~~~text
backend:8000/metrics
~~~

公共 Nginx 不再代理 `/metrics`。

Production runbook 同时包含 PostgreSQL backup/restore、Alembic upgrade/downgrade、安全
rollback、最终 smoke 和故障检查流程。
