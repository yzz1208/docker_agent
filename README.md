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
- Upgrade Phase 4：Vue 3 Web Product Shell（Step 1–2 ✅，Step 3 设置编辑下一步）

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

启动后端：

```powershell
uv run uvicorn docker_agent.main:app --reload
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
