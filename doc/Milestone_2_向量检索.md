# Milestone 2：BGE-M3 + PostgreSQL/pgvector 向量检索

这一阶段把 Milestone 1 生成的 `chunks.jsonl` 转成向量并写入 PostgreSQL/pgvector，最终能够使用自然语言查询 Docker 官方文档 Top-K。

## 1. 数据流

```text
chunks.jsonl
    ↓
Document title + Section path + Content
    ↓
BAAI/bge-m3
    ↓
1024-d normalized vector
    ↓
PostgreSQL / pgvector
    ↓
Query → BGE-M3 → cosine distance → Top-K
```

## 2. 为什么 Embedding 文本要带标题

实际写入模型的文本不是只有 chunk content，而是：

```text
Document: <title>
Section: <H1 > H2 > H3>
<content>
```

Docker 技术问题经常与标题、命令名和章节名强相关，因此保留结构元数据可以帮助召回。

## 3. 为什么先用 exact search

当前只有约 2,500 个 chunks，pgvector 精确 cosine search 已经足够快，而且便于后续做 Retrieval Eval。HNSW / IVFFlat 等近似索引等数据规模扩大后再加入，避免一开始引入额外变量。

## 4. 本地准备

更新依赖：

```powershell
uv sync --all-groups
```

第一次加载 BGE-M3 会下载模型。模型文件较大，如果不希望放系统盘，可在 `.env` 中设置：

```env
EMBEDDING_CACHE_DIR=F:/models/huggingface
```

设备可显式配置：

```env
EMBEDDING_DEVICE=cuda
```

如果 CUDA/PyTorch 环境暂时不可用，留空即可让 SentenceTransformers 选择可用设备。

## 5. 初始化向量表

确保 PostgreSQL 容器已启动：

```powershell
docker compose up -d postgres
```

然后：

```powershell
uv run python scripts/init_vector_store.py
```

预期：

```text
Vector store is ready: pgvector extension + document_chunks table
```

可以检查：

```powershell
docker compose exec postgres psql -U postgres -d docker_agent -c "\d document_chunks"
```

其中 `embedding` 应为 `vector(1024)`。

## 6. 先做小规模索引测试

不要第一次就直接跑全部 2582 个 chunks。先验证 20 条：

```powershell
uv run python scripts/index_chunks.py --reset --limit 20 --batch-size 8
```

第一次运行会加载/下载 BGE-M3，因此明显比之后慢。

检查行数：

```powershell
docker compose exec postgres psql -U postgres -d docker_agent -c "SELECT COUNT(*) FROM document_chunks;"
```

应返回 20。

## 7. 第一次向量搜索

```powershell
uv run python scripts/search_docs.py "Docker daemon 连不上怎么办" --top-k 5
```

或者：

```powershell
uv run python scripts/search_docs.py "difference between Docker volume and bind mount" --top-k 5
```

输出会包含：

- cosine similarity score
- title
- section path
- Docker Docs source URL
- chunk preview

BGE-M3 是多语言模型，因此后续会专门比较中文 query → 英文 Docker Docs 的跨语言检索效果。

## 8. 全量索引

小规模测试正常后：

```powershell
uv run python scripts/index_chunks.py --reset --batch-size 32
```

如果显存或内存不足，可把脚本 batch 调小；模型内部 embedding batch 由 `.env` 中的 `EMBEDDING_BATCH_SIZE` 控制，默认 8。

## 9. 当前验收标准

- `document_chunks` 表创建成功
- 20 条测试数据可以写入
- 中文和英文 query 都可以返回 Top-K
- source URL / section path / content 与原 JSONL 对应
- 全量索引最终行数与 `chunks.jsonl` 数量一致
- pytest / ruff 继续通过

## 10. 本阶段暂时不做

- BM25 / PostgreSQL Full Text Search
- Hybrid Search
- Reranker
- HNSW / IVFFlat
- LLM 生成答案

先把 dense retrieval 建立成可测量的 baseline。下一阶段再构建 Retrieval Eval，并以实验结果决定如何加入 keyword retrieval 和 rerank。
