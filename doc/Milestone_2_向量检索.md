# Milestone 2：BGE-M3 + PostgreSQL/pgvector 向量检索

这一阶段把 Milestone 1 生成的 `chunks.jsonl` 转成向量并写入 PostgreSQL/pgvector，最终能够使用自然语言查询 Docker 官方文档 Top-K，并建立可重复的检索评测基线。

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

当前只有约 2,500 个 chunks，pgvector 精确 cosine search 已经足够快，而且便于做 Retrieval Eval。HNSW / IVFFlat 等近似索引等数据规模扩大后再加入，避免一开始引入额外变量。

## 4. 本地准备

更新依赖：

```powershell
uv sync --all-groups
```

第一次加载 BGE-M3 会下载模型。模型文件较大，如果不希望放系统盘，可在 `.env` 中设置：

```env
EMBEDDING_CACHE_DIR=F:/models/huggingface
EMBEDDING_DEVICE=cuda
EMBEDDING_BATCH_SIZE=4
```

如果 CUDA/PyTorch 环境暂时不可用，可留空 `EMBEDDING_DEVICE` 让 SentenceTransformers 自动选择设备。

## 5. 初始化向量表

确保 PostgreSQL 容器已启动：

```powershell
docker compose up -d postgres
uv run python scripts/init_vector_store.py
```

检查表：

```powershell
docker compose exec postgres psql -U postgres -d docker_agent -c "\d document_chunks"
```

其中 `embedding` 应为 `vector(1024)`。

## 6. 小规模索引测试

第一次先验证少量 Chunk：

```powershell
uv run python scripts/index_chunks.py --reset --limit 20 --batch-size 4
```

检查行数：

```powershell
docker compose exec postgres psql -U postgres -d docker_agent -c "SELECT COUNT(*) FROM document_chunks;"
```

## 7. 向量搜索

```powershell
uv run python scripts/search_docs.py "Docker daemon 连不上怎么办" --top-k 5
```

输出包含 cosine similarity、title、section path、source URL 和 chunk preview。

## 8. 全量索引

小规模测试正常后：

```powershell
uv run python scripts/index_chunks.py --reset --batch-size 4
```

完成后数据库行数应与 `chunks.jsonl` 一致。

## 9. Retrieval Eval v1

最初的 `data/eval/retrieval_baseline.jsonl` 只有 6 条 smoke-test case，用来验证整个评测链路。它的查询相对简单，不应该把其高分理解为真实生产准确率。

## 10. Retrieval Eval v2

`data/eval/retrieval_v2.jsonl` 扩展到 30+ 条困难 case，覆盖：

- 中英文查询；
- 口语化故障描述；
- daemon / container / storage / network / compose；
- 错误症状与配置场景；
- 多相关文档问题；
- 部分 case 的 section-level 标注。

运行：

```powershell
uv run python scripts/eval_retrieval.py
```

评测脚本会先把标签与当前 `data/processed/chunks.jsonl` 对齐。如果 Docker Docs 路径或标题发生变化，会直接报出 stale label，而不是把错误标签静默算成检索失败。

默认输出两层指标。

### Document-level

- Hit@1 / Hit@3 / Hit@5
- Recall@1 / Recall@3 / Recall@5
- MRR

Document-level 只要求命中正确官方文档。

### Section-level

只有带 `relevant_section_terms` 的 case 参与：

- Section Hit@1 / Hit@3 / Hit@5
- Section MRR

Section-level 同时要求：

1. `file_path` 是相关文档；
2. `section_path` 命中人工标注的章节关键词。

这样可以区分“搜到了正确文档，但搜错了该文档里的章节”和“真正找到了可直接喂给 LLM 的上下文”。

## 11. 当前实验原则

先保存 Dense Retrieval 的真实 v2 指标，再决定是否加入 Keyword / Hybrid / Reranker。

推荐实验顺序：

```text
Dense baseline
    ↓
分析失败 case
    ↓
PostgreSQL keyword/full-text retrieval
    ↓
Dense + Keyword fusion
    ↓
重新跑同一套 eval
    ↓
如排序仍有问题，再加入 reranker
```

每次改动都使用同一评测集比较，不以单个 Demo 查询作为结论。

## 12. 当前阶段暂不做

- HNSW / IVFFlat
- LLM 生成答案
- Agent Tool Calling

先把 Retriever 做成可测量、可比较的稳定基础设施。
