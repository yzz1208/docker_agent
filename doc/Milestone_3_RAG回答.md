# Milestone 3：RAG Answer Generation

## 目标

把 Milestone 2 已确定的检索链：

~~~text
BGE-M3 Dense Top-20
        +
PostgreSQL FTS Top-20
        ↓
RRF Top-20
        ↓
BGE-reranker-v2-m3
        ↓
Top-5
~~~

接到可验证的回答生成链：

~~~text
Top-5
  ↓
Context Builder
  ↓
Grounded Prompt
  ↓
OpenAI-compatible Chat Model
  ↓
Answer + [n] citations + source URLs
~~~

## 新增模块

- rag/context.py：给 Chunk 分配 [1]、[2] 引用编号，保留标题、章节和 URL，并限制总上下文长度。
- rag/llm.py：最小 OpenAI-compatible /chat/completions 客户端。
- rag/answer.py：grounded prompt，要求只依据检索到的 Docker Docs 回答。
- scripts/ask_docs.py：第一版端到端命令行 RAG。

## .env

至少配置：

~~~env
MODEL_NAME=你的模型名
MODEL_BASE_URL=https://你的兼容服务/v1
MODEL_API_KEY=你的key
MODEL_TIMEOUT_SECONDS=60
MODEL_TEMPERATURE=0.1

RETRIEVAL_CANDIDATE_K=20
RETRIEVAL_RRF_K=60
RETRIEVAL_DENSE_WEIGHT=1.0
RETRIEVAL_KEYWORD_WEIGHT=1.0
RERANK_TOP_K=5
RAG_CONTEXT_MAX_CHARS=14000
~~~

如果使用不要求 API key 的本地 OpenAI-compatible 服务，MODEL_API_KEY 可以留空。

## 本地验证

~~~powershell
git fetch origin
git checkout feat/milestone-3-rag-answer
git pull --ff-only
uv sync --all-groups
uv run ruff check .
uv run pytest -v
~~~

确认数据库仍有 2582 条已索引 Chunk：

~~~powershell
docker compose up -d postgres
docker compose exec postgres psql -U postgres -d docker_agent -c "SELECT COUNT(*) FROM document_chunks;"
~~~

端到端测试：

~~~powershell
uv run python scripts/ask_docs.py "Docker daemon 连不上怎么办？"
uv run python scripts/ask_docs.py "Compose 里 web 必须等数据库健康后再启动，只写 depends_on 够吗？"
~~~

## 第一版验收标准

人工检查：

1. 回答中的 Docker 事实能否在打印出的 Sources 中找到依据。
2. [1] / [2] 是否真的指向支持该句结论的 Chunk。
3. 检索资料不足时，模型是否会承认不足。
4. 是否出现不存在的 Docker 命令、参数或配置项。
5. 中文提问时能否保持中文回答，同时引用英文官方文档。

完成这一阶段后建设 Answer Eval，再进入 Docker 工具调用与 Agent workflow。
