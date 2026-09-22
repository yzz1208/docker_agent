# Milestone 2：Hybrid Candidate Pool + BGE Reranker

## 1. 为什么现在进入 Reranker

37 条 retrieval v2 评测中，Hybrid 最终 Top-5 仍有排序误差，但 candidate coverage 已经达到：

```text
Dense Hit@10 = 0.9189
Dense Hit@20 = 1.0000
Keyword Hit@10 = 0.6216
Keyword Hit@20 = 0.7027
Union Hit@10 = 0.9459
Union Hit@20 = 1.0000
Union Recall@20 = 1.0000
```

这意味着当前 37 个 case 的正确文档都已经进入 Dense Top-20，Dense + Keyword union Top-20 也达到 100% 覆盖。

所以当前主要瓶颈从“召回不到”变成了“候选排序不够好”。这正是 cross-encoder reranker 适合解决的问题。

## 2. 当前检索链

```text
User Query
   │
   ├── BGE-M3 Dense Top-20
   │
   └── PostgreSQL FTS Top-20
              │
              ▼
        Weighted RRF merge
              │
              ▼
     最多约 40 个 unique candidates
              │
              ▼
    BAAI/bge-reranker-v2-m3
              │
              ▼
            Top-5
```

Reranker 与 embedding 模型不同：embedding 是分别编码 query/document 后做向量距离；reranker 把 query 和 candidate passage 成对输入模型，直接输出相关性分数，因此更慢，但排序能力更强。

## 3. 为什么选 bge-reranker-v2-m3

项目的 query 同时包含中文、英文和 Docker 技术词，而语料主要是英文 Docker Docs。`BAAI/bge-reranker-v2-m3` 是 multilingual reranker，并且与当前 BGE-M3 dense retrieval 技术栈一致。

当前实现直接使用 Hugging Face Transformers：

```text
AutoTokenizer
AutoModelForSequenceClassification
```

不额外引入 FlagEmbedding 运行时依赖。

## 4. GPU / 显存设计

本机显卡约 8 GB 显存。为了避免 embedding 模型与 reranker 同时常驻 GPU，`eval_retrieval.py --mode rerank` 会先一次性生成所有 query embedding，然后释放 BGE-M3，再加载 reranker。

默认配置：

```env
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_DEVICE=
RERANK_CACHE_DIR=
RERANK_BATCH_SIZE=4
RERANK_MAX_LENGTH=512
RERANK_USE_FP16=true
```

如果 `RERANK_DEVICE` 留空，会优先沿用 `EMBEDDING_DEVICE`；两者都为空时自动选择 CUDA 或 CPU。

建议本机 `.env`：

```env
EMBEDDING_DEVICE=cuda
EMBEDDING_CACHE_DIR=F:/models/huggingface
RERANK_DEVICE=cuda
RERANK_CACHE_DIR=F:/models/huggingface
RERANK_BATCH_SIZE=4
RERANK_USE_FP16=true
```

如果出现 CUDA out of memory，先把 `RERANK_BATCH_SIZE` 调成 2 或 1。

## 5. 单条查询测试

先同步依赖：

```powershell
uv sync --all-groups
```

第一次使用 reranker 会下载模型。

测试一个之前排序不稳定的问题：

```powershell
uv run python scripts/search_docs.py "Docker Compose 里 shell、.env、env_file 和 compose.yaml 都设置了同一个变量，到底谁覆盖谁？" --mode rerank --top-k 5
```

输出包含：

```text
rerank_score=...
rrf_score=...
dense_rank=...
keyword_rank=...
```

`rerank_score` 是 reranker logit 经 sigmoid 后的 0~1 分数，仅用于同一 query 下排序与观察，不应该直接当作全局置信度阈值。

## 6. 全量评测

先验证代码：

```powershell
uv run ruff check .
uv run pytest -v
```

然后：

```powershell
uv run python scripts/eval_retrieval.py --mode rerank
```

这一轮要直接和上一轮 Hybrid baseline 对比：

```text
Hybrid Document Hit@1 = 0.6757
Hybrid Document Hit@3 = 0.8649
Hybrid Document Hit@5 = 0.8919
Hybrid Document MRR   = 0.7635

Hybrid Section Hit@1 = 0.5455
Hybrid Section Hit@3 = 0.5455
Hybrid Section Hit@5 = 0.7273
Hybrid Section MRR   = 0.5864
```

重点观察：

- Document Hit@1 / MRR 是否提升
- Section Hit@1 / MRR 是否提升
- 已经 Top-1 正确的 query 有没有被 reranker 破坏
- 原本 `doc_rank=MISS` 但 candidate union@20=HIT 的 query 是否被救回

## 7. 下一步决策

如果 Reranker 明显提升 Top-1 / MRR，则 Milestone 2 的 retrieval pipeline 基本完成，下一步进入 Context Builder + LLM Answer Generation。

如果提升很小或出现明显退化，先做失败样本分析，再决定：

- rerank passage 是否过长
- max_length 是否需要调整
- candidate pool 是否需要先做 document/section 去重
- Weighted RRF 是否应作为 reranker 前的候选优先级
- 是否要改成只 rerank Top-20 fused candidates，而不是完整 union pool
