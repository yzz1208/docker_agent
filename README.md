# Docker Support Agent

基于 Docker 官方开源文档逐步实现的技术支持 Agent。项目按 **数据管道 → RAG → Tool Calling → Agent Workflow → Evaluation** 的顺序推进。

完整设计见：[`doc/Docker_Support_Agent_开发文档.md`](doc/Docker_Support_Agent_开发文档.md)。

## 当前进度

- [x] Python 3.12 + uv 项目结构
- [x] FastAPI 基础服务
- [x] PostgreSQL 16 + pgvector
- [x] `/health` 与 `/health/db`
- [x] Docker Docs 下载脚本
- [x] 文档白名单筛选
- [x] YAML Front Matter 解析
- [x] Markdown 清洗与 Heading 分段
- [x] 生成 `documents.jsonl` / `chunks.jsonl`
- [ ] Embedding + pgvector 索引
- [ ] Hybrid Retrieval + Rerank
- [ ] Tool Calling
- [ ] LangGraph Agent
- [ ] Evaluation

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop / Docker Engine
- Git

当前阶段不需要配置大模型 API Key。

## 本地启动

### 1. 拉取当前开发分支

```powershell
git fetch
git checkout feat/milestone-1-docs-pipeline
git pull
```

### 2. 安装依赖

```powershell
uv sync --all-groups
```

### 3. 创建本地配置

```powershell
Copy-Item .env.example .env
```

### 4. 启动 PostgreSQL + pgvector

```powershell
docker compose up -d postgres
docker compose ps
```

### 5. 启动 FastAPI

```powershell
uv run uvicorn docker_agent.main:app --reload
```

浏览器打开：

```text
http://127.0.0.1:8000/docs
```

数据库检查：

```text
GET /health/db
```

## Milestone 1：构建 Docker Docs 数据集

Docker Docs 官方仓库当前的内容主要位于 `content/`，本项目 V1 只选取以下范围：

```text
content/get-started/
content/manuals/engine/
content/manuals/compose/
```

这样先控制知识库范围，后续再根据评测结果决定是否扩充。

### 1. 下载 / 更新 Docker Docs

```powershell
uv run python scripts/download_docs.py
```

首次运行会 shallow clone：

```text
data/raw/docker-docs/
```

以后再次执行会 fetch 最新 `main` 并更新本地 raw 数据。

### 2. 筛选文档

```powershell
uv run python scripts/select_docs.py
```

输出：

```text
data/selected/docker-docs/
```

脚本会保留 Docker Docs 原始目录结构，方便后续追踪原文来源。

### 3. 清洗、分段并生成 JSONL

```powershell
uv run python scripts/build_docs.py
```

输出：

```text
data/processed/documents.jsonl
data/processed/chunks.jsonl
```

`documents.jsonl` 每行代表一篇清洗后的官方文档；`chunks.jsonl` 每行代表后续 RAG 的一个检索单元。

### 4. 快速查看结果

PowerShell：

```powershell
Get-Content data/processed/documents.jsonl -TotalCount 1
Get-Content data/processed/chunks.jsonl -TotalCount 3
```

可以重点检查：

- `title` 是否正确；
- `section_path` 是否能反映 Markdown 标题层级；
- Docker 命令和错误文本是否保留；
- `source_url` 是否指向对应 `docs.docker.com` 页面；
- 代码块有没有被误当成 Markdown Heading。

## 数据处理设计

### Front Matter

Docker Docs Markdown 常见：

```markdown
---
title: Troubleshooting Docker
---
```

使用 PyYAML 解析 metadata，正文与 metadata 分离。

### Markdown 清洗

V1 不追求把 Markdown 转成纯文本，而是尽量保留对技术检索有价值的结构：

保留：

- 正文；
- 列表；
- 命令；
- fenced code block；
- 错误信息；
- note / tip 内部文本。

删除：

- 单独一行的 Hugo / Docker Docs 展示 shortcode。

### Heading 分段

先按：

```text
# H1
## H2
### H3
```

构造 `section_path`，并显式忽略代码块中的 `#`，例如 Shell comment 不会被识别成文档标题。

较长 section 再按段落切分。当前默认：

```text
max_words = 450
overlap_words = 60
```

这里暂时使用 word count，而不是某个 Embedding 模型的 tokenizer。进入 Embedding 阶段后，会根据最终选定的模型重新评估 chunk token 分布。

## 数据结构

Document 示例：

```json
{
  "document_id": "docker_document_...",
  "source": "docker_docs",
  "file_path": "content/manuals/engine/daemon/troubleshoot.md",
  "title": "Troubleshoot the Docker daemon",
  "source_url": "https://docs.docker.com/engine/daemon/troubleshoot/",
  "language": "en",
  "content": "..."
}
```

Chunk 示例：

```json
{
  "chunk_id": "docker_document_...__0001",
  "document_id": "docker_document_...",
  "title": "Troubleshoot the Docker daemon",
  "section_path": ["Troubleshoot the Docker daemon", "..."],
  "content": "...",
  "source_url": "https://docs.docker.com/engine/daemon/troubleshoot/",
  "file_path": "content/manuals/engine/daemon/troubleshoot.md",
  "word_count": 312
}
```

## 测试

```powershell
uv run pytest -v
uv run ruff check .
```

当前 Markdown 测试覆盖：

- YAML Front Matter；
- Heading hierarchy；
- 代码块内部 `#` 不被误识别；
- shortcode wrapper 清理；
- Docker Docs URL 映射；
- 长 section 二次切分。

## 项目结构

```text
docker_agent/
├── doc/
├── docker/
│   └── postgres/init/
├── scripts/
│   ├── download_docs.py
│   ├── select_docs.py
│   └── build_docs.py
├── src/docker_agent/
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   └── docs/
│       ├── models.py
│       ├── markdown.py
│       └── pipeline.py
├── tests/
│   ├── test_health.py
│   └── test_docs_markdown.py
├── compose.yaml
└── pyproject.toml
```

## 为什么暂时不把数据写进 PostgreSQL

Milestone 1 的目标是先验证：

```text
官方 Markdown
→ 清洗
→ 结构化 Document
→ Chunk
```

因此先输出 JSONL，方便人工检查和重复构建。

下一阶段确认数据质量后，再做：

```text
chunks.jsonl
    ↓
Embedding
    ↓
PostgreSQL + pgvector
    ↓
Vector Retrieval
```

这样出现检索问题时，可以明确区分是“原始数据 / Chunk 问题”还是“Embedding / 数据库问题”。
